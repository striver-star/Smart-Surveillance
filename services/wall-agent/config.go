package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
)

// Config is read from a JSON file written by the installer.
type Config struct {
	PlatformURL         string   `json:"platform_url"`          // e.g. https://hss.example.local
	NodeID              string   `json:"node_id"`               // e.g. wall-pc-1
	Token               string   `json:"token"`                 // shared wall token; HSS_WALL_TOKEN overrides
	Browser             string   `json:"browser"`               // browser executable; empty = auto-detect
	ExtraBrowserArgs    []string `json:"extra_browser_args"`    // added to every browser start
	DefaultPath         string   `json:"default_path"`          // page used before the platform sends a layout
	LocalPort           int      `json:"local_port"`            // page heartbeats arrive on 127.0.0.1:port
	HeartbeatSeconds    int      `json:"heartbeat_seconds"`     // agent -> platform
	PageTimeoutSeconds  int      `json:"page_timeout_seconds"`  // restart a browser after this long without a page heartbeat
	StartupGraceSeconds int      `json:"startup_grace_seconds"` // time a new browser gets before the first heartbeat is required
	CAFile              string   `json:"ca_file"`               // extra CA certificate (PEM) for the platform
	InsecureTLS         bool     `json:"insecure_tls"`          // test only
	DataDir             string   `json:"data_dir"`              // browser profiles, layout cache, log
}

var nodeIDPattern = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)

func defaultConfigPath() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("ProgramData"), "HSS", "WallAgent", "config.json")
	}
	return "/etc/hss-wall-agent/config.json"
}

func defaultDataDir() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("LOCALAPPDATA"), "HSS", "WallAgent")
	}
	if d := os.Getenv("XDG_STATE_HOME"); d != "" {
		return filepath.Join(d, "hss-wall-agent")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".local", "state", "hss-wall-agent")
}

func loadConfig(path string) (*Config, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	c := &Config{}
	if err := json.Unmarshal(raw, c); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if t := os.Getenv("HSS_WALL_TOKEN"); t != "" {
		c.Token = t
	}
	c.applyDefaults()
	return c, c.validate()
}

func (c *Config) applyDefaults() {
	if c.LocalPort == 0 {
		c.LocalPort = 17311
	}
	if c.HeartbeatSeconds == 0 {
		c.HeartbeatSeconds = 15
	}
	if c.PageTimeoutSeconds == 0 {
		c.PageTimeoutSeconds = 30
	}
	if c.StartupGraceSeconds == 0 {
		c.StartupGraceSeconds = 60
	}
	if c.DefaultPath == "" {
		c.DefaultPath = "/wall-test/"
	}
	if c.DataDir == "" {
		c.DataDir = defaultDataDir()
	}
}

func (c *Config) validate() error {
	u, err := url.Parse(c.PlatformURL)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" {
		return fmt.Errorf("platform_url must be like https://server, got %q", c.PlatformURL)
	}
	if !nodeIDPattern.MatchString(c.NodeID) {
		return fmt.Errorf("node_id must be 1-64 letters, digits, dot, dash or underscore, got %q", c.NodeID)
	}
	if c.Token == "" {
		return errors.New("token is empty (set it in the config or HSS_WALL_TOKEN)")
	}
	if _, err := resolvePage(u, c.DefaultPath); err != nil {
		return fmt.Errorf("default_path: %w", err)
	}
	return nil
}

func (c *Config) platform() *url.URL {
	u, _ := url.Parse(c.PlatformURL)
	return u
}
