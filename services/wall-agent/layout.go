package main

import (
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// MonitorLayout says which platform page a monitor shows.
type MonitorLayout struct {
	Monitor int    `json:"monitor"`
	Path    string `json:"path"`
}

// resolvePage turns a layout path into a full URL on the platform. Only paths on the platform
// itself are accepted, so a bad layout can never send a wall screen to another site.
func resolvePage(platform *url.URL, path string) (*url.URL, error) {
	if !strings.HasPrefix(path, "/") || strings.HasPrefix(path, "//") || strings.Contains(path, "\\") {
		return nil, errors.New("path must start with a single / and stay on the platform")
	}
	ref, err := url.Parse(path)
	if err != nil {
		return nil, err
	}
	if ref.Scheme != "" || ref.Host != "" || ref.User != nil {
		return nil, errors.New("path must not contain a scheme or host")
	}
	return platform.ResolveReference(ref), nil
}

// pageURL adds the parameters the page needs to send heartbeats back to this agent.
func pageURL(platform *url.URL, path string, monitor, port int, node string) (string, error) {
	u, err := resolvePage(platform, path)
	if err != nil {
		return "", err
	}
	q := u.Query()
	q.Set("wall_agent", "http://127.0.0.1:"+strconv.Itoa(port))
	q.Set("monitor", strconv.Itoa(monitor))
	q.Set("node", node)
	u.RawQuery = q.Encode()
	return u.String(), nil
}

func layoutCachePath(dataDir string) string { return filepath.Join(dataDir, "layout.json") }

func saveLayout(dataDir string, layout []MonitorLayout) error {
	raw, err := json.MarshalIndent(layout, "", "  ")
	if err != nil {
		return err
	}
	tmp := layoutCachePath(dataDir) + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, layoutCachePath(dataDir))
}

func loadLayout(dataDir string) []MonitorLayout {
	raw, err := os.ReadFile(layoutCachePath(dataDir))
	if err != nil {
		return nil
	}
	var layout []MonitorLayout
	if json.Unmarshal(raw, &layout) != nil {
		return nil
	}
	return layout
}
