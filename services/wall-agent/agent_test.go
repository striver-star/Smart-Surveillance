package main

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func testConfig(t *testing.T) *Config {
	c := &Config{PlatformURL: "https://hss.local", NodeID: "wall-pc-1", Token: "t", DataDir: t.TempDir()}
	c.applyDefaults()
	if err := c.validate(); err != nil {
		t.Fatal(err)
	}
	return c
}

func TestResolvePageStaysOnPlatform(t *testing.T) {
	p, _ := url.Parse("https://hss.local")
	good, err := resolvePage(p, "/wall/grid?nvr=nvr1")
	if err != nil || good.String() != "https://hss.local/wall/grid?nvr=nvr1" {
		t.Fatalf("got %v %v", good, err)
	}
	for _, bad := range []string{"https://evil.example/", "//evil.example/x", "wall", `/\evil`, "javascript:alert(1)"} {
		if _, err := resolvePage(p, bad); err == nil {
			t.Errorf("%q was accepted", bad)
		}
	}
}

func TestPageURLAddsAgentParameters(t *testing.T) {
	p, _ := url.Parse("https://hss.local")
	u, err := pageURL(p, "/wall-test/?n=32", 1, 17311, "wall-pc-1")
	if err != nil {
		t.Fatal(err)
	}
	parsed, _ := url.Parse(u)
	q := parsed.Query()
	if q.Get("n") != "32" || q.Get("monitor") != "1" || q.Get("wall_agent") != "http://127.0.0.1:17311" || q.Get("node") != "wall-pc-1" {
		t.Fatalf("bad url %s", u)
	}
}

func TestConfigRejectsBadValues(t *testing.T) {
	for _, c := range []Config{
		{PlatformURL: "ftp://x", NodeID: "a", Token: "t"},
		{PlatformURL: "https://x", NodeID: "bad id", Token: "t"},
		{PlatformURL: "https://x", NodeID: "a"},
		{PlatformURL: "https://x", NodeID: "a", Token: "t", DefaultPath: "https://evil/"},
	} {
		c.applyDefaults()
		if c.validate() == nil {
			t.Errorf("accepted %+v", c)
		}
	}
}

// fakeSupervisor replaces process start and stop with counters and uses a manual clock.
func fakeSupervisor(t *testing.T) (*Supervisor, *time.Time, *int, *int) {
	cfg := testConfig(t)
	cfg.StartupGraceSeconds, cfg.PageTimeoutSeconds = 60, 30
	sv := NewSupervisor(cfg, "/bin/true")
	now := time.Date(2026, 10, 28, 12, 0, 0, 0, time.UTC)
	launches, kills := 0, 0
	sv.now = func() time.Time { return now }
	sv.launch = func(s *Slot) error { launches++; s.exited = make(chan struct{}); return nil }
	sv.kill = func(s *Slot) { kills++ }
	return sv, &now, &launches, &kills
}

var twoTVs = []Monitor{{Index: 0, Width: 1920, Height: 1080}, {Index: 1, X: 1920, Width: 1920, Height: 1080}}

func TestSupervisorStartsOneBrowserPerMonitor(t *testing.T) {
	sv, _, launches, _ := fakeSupervisor(t)
	sv.Reconcile(twoTVs, []MonitorLayout{{Monitor: 1, Path: "/wall/rotation"}})
	sv.Check()
	st := sv.Status()
	if *launches != 2 || len(st) != 2 {
		t.Fatalf("launches %d, status %d", *launches, len(st))
	}
	if !strings.Contains(st[0].URL, "/wall-test/") || !strings.Contains(st[1].URL, "/wall/rotation") {
		t.Fatalf("urls %s %s", st[0].URL, st[1].URL)
	}
}

func TestSupervisorRestartsFrozenPageWithBackoff(t *testing.T) {
	sv, now, launches, kills := fakeSupervisor(t)
	sv.Reconcile(twoTVs[:1], nil)
	sv.Check()
	*now = now.Add(10 * time.Second)
	sv.PageHeartbeat(0, []byte(`{}`))
	*now = now.Add(45 * time.Second) // 55 s after start: inside the 60 s start-up grace
	sv.Check()
	if *kills != 0 {
		t.Fatal("killed during grace period")
	}
	*now = now.Add(10 * time.Second) // 65 s after start, last page heartbeat 55 s ago
	sv.Check()
	if *kills != 1 || sv.Status()[0].LastRestart != "page stopped responding" {
		t.Fatalf("kills %d, status %+v", *kills, sv.Status()[0])
	}
	sv.Check() // the 2 s backoff is not over yet
	if *launches != 1 {
		t.Fatal("restarted before backoff")
	}
	*now = now.Add(2 * time.Second)
	sv.Check()
	if *launches != 2 {
		t.Fatalf("launches %d", *launches)
	}
}

func TestSupervisorRestartsCrashedBrowser(t *testing.T) {
	sv, now, launches, _ := fakeSupervisor(t)
	sv.Reconcile(twoTVs[:1], nil)
	sv.Check()
	close(sv.slots[0].exited)
	sv.Check()
	if sv.Status()[0].LastRestart != "browser exited" {
		t.Fatalf("%+v", sv.Status()[0])
	}
	*now = now.Add(3 * time.Second)
	sv.Check()
	if *launches != 2 {
		t.Fatalf("launches %d", *launches)
	}
}

func TestSupervisorReopensOnLayoutChangeAndClosesRemovedMonitor(t *testing.T) {
	sv, _, launches, kills := fakeSupervisor(t)
	sv.Reconcile(twoTVs, nil)
	sv.Check()
	sv.Reconcile(twoTVs, []MonitorLayout{{Monitor: 0, Path: "/wall/grid?nvr=nvr2"}})
	sv.Check()
	if *kills != 1 || *launches != 3 {
		t.Fatalf("kills %d launches %d", *kills, *launches)
	}
	sv.Reconcile(twoTVs[:1], []MonitorLayout{{Monitor: 0, Path: "/wall/grid?nvr=nvr2"}})
	if *kills != 2 || len(sv.Status()) != 1 {
		t.Fatalf("kills %d, screens %d", *kills, len(sv.Status()))
	}
}

func TestLocalServerOnlyAcceptsPlatformOrigin(t *testing.T) {
	sv, _, _, _ := fakeSupervisor(t)
	sv.Reconcile(twoTVs[:1], nil)
	sv.Check()
	h := localServer(sv.cfg, sv, func() any { return nil }).Handler

	pre := httptest.NewRequest(http.MethodOptions, "/heartbeat?monitor=0", nil)
	pre.Header.Set("Origin", "https://hss.local")
	pre.Header.Set("Access-Control-Request-Private-Network", "true")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, pre)
	if w.Code != http.StatusNoContent || w.Header().Get("Access-Control-Allow-Private-Network") != "true" {
		t.Fatalf("preflight %d %v", w.Code, w.Header())
	}

	ok := httptest.NewRequest(http.MethodPost, "/heartbeat?monitor=0", strings.NewReader(`{"playing":32}`))
	ok.Header.Set("Origin", "https://hss.local")
	w = httptest.NewRecorder()
	h.ServeHTTP(w, ok)
	if w.Code != http.StatusNoContent || sv.Status()[0].PageAgeSecs == nil {
		t.Fatalf("heartbeat %d", w.Code)
	}

	evil := httptest.NewRequest(http.MethodPost, "/heartbeat?monitor=0", strings.NewReader(`{}`))
	evil.Header.Set("Origin", "https://evil.example")
	w = httptest.NewRecorder()
	h.ServeHTTP(w, evil)
	if w.Code != http.StatusForbidden {
		t.Fatalf("foreign origin got %d", w.Code)
	}
}

func TestInstallUpdateChecksChecksum(t *testing.T) {
	dir := t.TempDir()
	exe := filepath.Join(dir, "hss-wall-agent")
	os.WriteFile(exe, []byte("old"), 0o755)
	data := []byte(strings.Repeat("new agent ", 200))
	sum := sha256.Sum256(data)
	if err := installUpdate(exe, data, strings.Repeat("0", 64)); err == nil {
		t.Fatal("accepted a wrong checksum")
	}
	if got, _ := os.ReadFile(exe); string(got) != "old" {
		t.Fatal("old executable changed after a failed update")
	}
	if err := installUpdate(exe, data, hex.EncodeToString(sum[:])); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(exe); string(got) != string(data) {
		t.Fatal("new executable not in place")
	}
}

func TestLayoutCacheRoundTrip(t *testing.T) {
	dir := t.TempDir()
	want := []MonitorLayout{{Monitor: 0, Path: "/wall/grid?nvr=nvr1"}}
	if err := saveLayout(dir, want); err != nil {
		t.Fatal(err)
	}
	if got := loadLayout(dir); !sameLayout(got, want) {
		t.Fatalf("got %+v", got)
	}
}
