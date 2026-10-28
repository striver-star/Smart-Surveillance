package main

import (
	"encoding/json"
	"log"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"time"
)

const (
	minBackoff     = 2 * time.Second
	maxBackoff     = 60 * time.Second
	healthyToReset = 5 * time.Minute
)

// Slot is the browser window for one monitor.
type Slot struct {
	Monitor   Monitor
	URL       string
	cmd       *exec.Cmd
	running   bool
	exited    chan struct{}
	startedAt time.Time
	lastPage  time.Time
	page      json.RawMessage
	restarts  int
	reason    string
	backoff   time.Duration
	nextStart time.Time
}

// SlotStatus is what the platform sees for each monitor.
type SlotStatus struct {
	Monitor      Monitor         `json:"monitor"`
	URL          string          `json:"url"`
	Running      bool            `json:"running"`
	PID          int             `json:"pid,omitempty"`
	UpSeconds    int             `json:"up_seconds"`
	PageAgeSecs  *int            `json:"page_heartbeat_age_s"`
	Restarts     int             `json:"restarts"`
	LastRestart  string          `json:"last_restart_reason,omitempty"`
	PageSnapshot json.RawMessage `json:"page,omitempty"`
}

// Supervisor keeps one kiosk browser per monitor running and restarts any that crash or hang.
type Supervisor struct {
	mu      sync.Mutex
	cfg     *Config
	browser string
	slots   map[int]*Slot
	now     func() time.Time
	launch  func(s *Slot) error
	kill    func(s *Slot)
}

func NewSupervisor(cfg *Config, browser string) *Supervisor {
	sv := &Supervisor{cfg: cfg, browser: browser, slots: map[int]*Slot{}, now: time.Now}
	sv.launch = sv.launchBrowser
	sv.kill = func(s *Slot) { killTree(s.cmd) }
	return sv
}

func (sv *Supervisor) launchBrowser(s *Slot) error {
	profile := filepath.Join(sv.cfg.DataDir, "profiles", "monitor-"+strconv.Itoa(s.Monitor.Index))
	cmd := browserCommand(sv.browser, s.Monitor, s.URL, profile, sv.cfg.ExtraBrowserArgs)
	if err := cmd.Start(); err != nil {
		return err
	}
	s.cmd = cmd
	s.exited = make(chan struct{})
	go func(done chan struct{}) { _ = cmd.Wait(); close(done) }(s.exited)
	return nil
}

// Reconcile matches browser windows to the current monitors and layout.
func (sv *Supervisor) Reconcile(monitors []Monitor, layout []MonitorLayout) {
	sv.mu.Lock()
	defer sv.mu.Unlock()
	paths := map[int]string{}
	for _, l := range layout {
		paths[l.Monitor] = l.Path
	}
	wanted := map[int]bool{}
	for _, m := range monitors {
		path, ok := paths[m.Index]
		if !ok {
			path = sv.cfg.DefaultPath
		}
		u, err := pageURL(sv.cfg.platform(), path, m.Index, sv.cfg.LocalPort, sv.cfg.NodeID)
		if err != nil {
			log.Printf("monitor %d: ignoring layout path %q: %v", m.Index, path, err)
			if u, err = pageURL(sv.cfg.platform(), sv.cfg.DefaultPath, m.Index, sv.cfg.LocalPort, sv.cfg.NodeID); err != nil {
				continue
			}
		}
		wanted[m.Index] = true
		if s, ok := sv.slots[m.Index]; ok && s.URL == u && s.Monitor == m {
			continue
		} else if ok {
			log.Printf("monitor %d: layout or position changed, reopening", m.Index)
			sv.stopLocked(s)
		}
		sv.slots[m.Index] = &Slot{Monitor: m, URL: u, backoff: minBackoff, nextStart: sv.now()}
	}
	for i, s := range sv.slots {
		if !wanted[i] {
			log.Printf("monitor %d: no longer connected, closing its browser", i)
			sv.stopLocked(s)
			delete(sv.slots, i)
		}
	}
}

// Check starts missing browsers and restarts crashed or frozen ones. Call it every few seconds.
func (sv *Supervisor) Check() {
	sv.mu.Lock()
	defer sv.mu.Unlock()
	now := sv.now()
	grace := time.Duration(sv.cfg.StartupGraceSeconds) * time.Second
	timeout := time.Duration(sv.cfg.PageTimeoutSeconds) * time.Second
	for _, s := range sv.slots {
		if s.running {
			select {
			case <-s.exited:
				sv.scheduleRestart(s, "browser exited")
				continue
			default:
			}
			deadline := s.startedAt.Add(grace)
			if !s.lastPage.IsZero() && s.lastPage.Add(timeout).After(deadline) {
				deadline = s.lastPage.Add(timeout)
			}
			if now.After(deadline) {
				reason := "page stopped responding"
				if s.lastPage.IsZero() {
					reason = "page never responded"
				}
				sv.kill(s)
				sv.scheduleRestart(s, reason)
				continue
			}
			if !s.lastPage.IsZero() && now.Sub(s.startedAt) > healthyToReset {
				s.backoff = minBackoff
			}
			continue
		}
		if now.Before(s.nextStart) {
			continue
		}
		if err := sv.launch(s); err != nil {
			log.Printf("monitor %d: cannot start browser: %v", s.Monitor.Index, err)
			sv.scheduleRestart(s, "start failed: "+err.Error())
			continue
		}
		s.running, s.startedAt, s.lastPage, s.page = true, now, time.Time{}, nil
		log.Printf("monitor %d: browser started on %s", s.Monitor.Index, s.Monitor)
	}
}

func (sv *Supervisor) scheduleRestart(s *Slot, reason string) {
	s.running = false
	s.restarts++
	s.reason = reason
	s.nextStart = sv.now().Add(s.backoff)
	log.Printf("monitor %d: %s; restarting in %s", s.Monitor.Index, reason, s.backoff)
	s.backoff *= 2
	if s.backoff > maxBackoff {
		s.backoff = maxBackoff
	}
}

func (sv *Supervisor) stopLocked(s *Slot) {
	if s.running {
		sv.kill(s)
		s.running = false
	}
}

// StopAll closes every browser, for shutdown and self-update.
func (sv *Supervisor) StopAll() {
	sv.mu.Lock()
	defer sv.mu.Unlock()
	for _, s := range sv.slots {
		sv.stopLocked(s)
	}
}

// PageHeartbeat records that the page on a monitor is alive.
func (sv *Supervisor) PageHeartbeat(monitor int, body json.RawMessage) bool {
	sv.mu.Lock()
	defer sv.mu.Unlock()
	s, ok := sv.slots[monitor]
	if !ok || !s.running {
		return false
	}
	s.lastPage, s.page = sv.now(), body
	return true
}

func (sv *Supervisor) Status() []SlotStatus {
	sv.mu.Lock()
	defer sv.mu.Unlock()
	now := sv.now()
	out := make([]SlotStatus, 0, len(sv.slots))
	for i := 0; len(out) < len(sv.slots); i++ {
		s, ok := sv.slots[i]
		if !ok {
			if i > 1000 {
				break
			}
			continue
		}
		st := SlotStatus{Monitor: s.Monitor, URL: s.URL, Running: s.running, Restarts: s.restarts,
			LastRestart: s.reason, PageSnapshot: s.page}
		if s.running {
			st.UpSeconds = int(now.Sub(s.startedAt).Seconds())
			if s.cmd != nil && s.cmd.Process != nil {
				st.PID = s.cmd.Process.Pid
			}
		}
		if !s.lastPage.IsZero() {
			age := int(now.Sub(s.lastPage).Seconds())
			st.PageAgeSecs = &age
		}
		out = append(out, st)
	}
	return out
}
