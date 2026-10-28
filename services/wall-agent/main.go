// Command hss-wall-agent runs on each wall PC. It opens a kiosk browser on every monitor with the
// page the platform assigns, restarts browsers that crash or freeze, reports health to the
// platform, keeps working from a cached layout when the platform is unreachable, and updates itself.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"
)

// Version is set at build time with -ldflags "-X main.Version=...".
var Version = "dev"

func main() {
	configPath := flag.String("config", defaultConfigPath(), "configuration file")
	showVersion := flag.Bool("version", false, "print the version and exit")
	showMonitors := flag.Bool("monitors", false, "list the monitors this PC reports and exit")
	flag.Parse()

	if *showVersion {
		fmt.Println(Version)
		return
	}
	if *showMonitors {
		ms, err := listMonitors()
		if err != nil {
			fmt.Fprintln(os.Stderr, "cannot list monitors:", err)
			os.Exit(1)
		}
		for _, m := range ms {
			fmt.Println(m)
		}
		return
	}

	cfg, err := loadConfig(*configPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "configuration:", err)
		os.Exit(2)
	}
	if err := os.MkdirAll(cfg.DataDir, 0o700); err != nil {
		fmt.Fprintln(os.Stderr, "data dir:", err)
		os.Exit(2)
	}
	setupLog(filepath.Join(cfg.DataDir, "agent.log"))
	os.Exit(run(cfg))
}

func run(cfg *Config) int {
	exe, _ := os.Executable()
	cleanupOldExecutable(exe)
	log.Printf("hss-wall-agent %s starting: node %s, platform %s", Version, cfg.NodeID, cfg.PlatformURL)

	browser, err := findBrowser(cfg.Browser)
	if err != nil {
		log.Print(err)
		return 2
	}
	log.Printf("browser: %s", browser)
	client, err := newPlatformClient(cfg)
	if err != nil {
		log.Printf("platform client: %v", err)
		return 2
	}

	sv := NewSupervisor(cfg, browser)
	started := time.Now()
	cpu := &cpuMeter{}
	cpu.Percent()
	var monitors []Monitor
	layout := loadLayout(cfg.DataDir)
	if layout != nil {
		log.Printf("using cached layout for %d monitor(s) until the platform answers", len(layout))
	}
	health := func() Health {
		mem, total := memoryUsage()
		return Health{NodeID: cfg.NodeID, Hostname: hostname(), AgentVersion: Version, OS: osName(),
			Arch: archName(), Browser: filepath.Base(browser), UptimeSeconds: int(time.Since(started).Seconds()),
			CPUPercent: cpu.Percent(), MemoryPercent: mem, MemoryTotalMB: total, Monitors: monitors,
			Screens: sv.Status()}
	}
	srv := localServer(cfg, sv, func() any { return map[string]any{"version": Version, "screens": sv.Status()} })
	go serveLocal(srv)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	refreshMonitors := func() {
		ms, err := listMonitors()
		if err != nil || len(ms) == 0 {
			log.Printf("cannot list monitors (%v); keeping the previous list", err)
			return
		}
		if !sameMonitors(ms, monitors) {
			for _, m := range ms {
				log.Printf("monitor %s", m)
			}
			monitors = ms
		}
	}
	refreshMonitors()
	sv.Reconcile(monitors, layout)
	sv.Check()

	check := time.NewTicker(2 * time.Second)
	beat := time.NewTicker(time.Duration(cfg.HeartbeatSeconds) * time.Second)
	defer check.Stop()
	defer beat.Stop()
	platformOK := true
	exitCode := 0
	heartbeat := func() {
		reply, err := client.Heartbeat(health())
		if err != nil {
			if platformOK {
				log.Printf("platform unreachable, wall keeps running on the cached layout: %v", err)
			}
			platformOK = false
			return
		}
		if !platformOK {
			log.Print("platform reachable again")
		}
		platformOK = true
		if reply.Layout != nil && !sameLayout(reply.Layout, layout) {
			log.Printf("new layout from platform for %d monitor(s)", len(reply.Layout))
			layout = reply.Layout
			if err := saveLayout(cfg.DataDir, layout); err != nil {
				log.Printf("cannot cache layout: %v", err)
			}
			sv.Reconcile(monitors, layout)
		}
		if a := reply.Agent; a != nil && a.Version != "" && a.Version != Version && a.Path != "" {
			log.Printf("updating agent %s -> %s", Version, a.Version)
			data, err := client.Download(a.Path, 100<<20)
			if err == nil {
				err = installUpdate(exe, data, a.SHA256)
			}
			if err != nil {
				log.Printf("update failed, staying on %s: %v", Version, err)
				return
			}
			log.Printf("update installed; restarting")
			exitCode = exitUpdated
			stop()
		}
	}
	heartbeat()
	for ctx.Err() == nil {
		select {
		case <-ctx.Done():
		case <-check.C:
			refreshMonitors()
			sv.Reconcile(monitors, layout)
			sv.Check()
		case <-beat.C:
			heartbeat()
		}
	}
	log.Print("stopping: closing browsers")
	sv.StopAll()
	shutdown, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdown)
	return exitCode
}

func sameLayout(a, b []MonitorLayout) bool {
	x, _ := json.Marshal(a)
	y, _ := json.Marshal(b)
	return string(x) == string(y)
}

// setupLog writes to agent.log (kept under 5 MB, one old copy) and to stderr when there is one.
func setupLog(path string) {
	if st, err := os.Stat(path); err == nil && st.Size() > 5<<20 {
		_ = os.Rename(path, path+".1")
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	log.SetOutput(io.MultiWriter(f, os.Stderr))
	log.SetFlags(log.LstdFlags)
}
