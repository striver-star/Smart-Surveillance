package main

import (
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"runtime"
	"time"
)

// Health is sent to the platform on every heartbeat.
type Health struct {
	NodeID        string       `json:"node_id"`
	Hostname      string       `json:"hostname"`
	AgentVersion  string       `json:"agent_version"`
	OS            string       `json:"os"`
	Arch          string       `json:"arch"`
	Browser       string       `json:"browser"`
	UptimeSeconds int          `json:"agent_uptime_s"`
	CPUPercent    float64      `json:"cpu_percent"`
	MemoryPercent float64      `json:"memory_percent"`
	MemoryTotalMB uint64       `json:"memory_total_mb"`
	Monitors      []Monitor    `json:"monitors"`
	Screens       []SlotStatus `json:"screens"`
}

// AgentRelease tells the agent which version it should run.
type AgentRelease struct {
	Version string `json:"version"`
	Path    string `json:"path"`
	SHA256  string `json:"sha256"`
}

// HeartbeatReply is the platform's answer: the layout to show and the wanted agent version.
type HeartbeatReply struct {
	Layout []MonitorLayout `json:"layout"`
	Agent  *AgentRelease   `json:"agent"`
}

type platformClient struct {
	cfg  *Config
	http *http.Client
}

func newPlatformClient(cfg *Config) (*platformClient, error) {
	tlsCfg := &tls.Config{MinVersion: tls.VersionTLS12, InsecureSkipVerify: cfg.InsecureTLS} //nolint:gosec // test option, off by default
	if cfg.CAFile != "" {
		pem, err := os.ReadFile(cfg.CAFile)
		if err != nil {
			return nil, err
		}
		pool, err := x509.SystemCertPool()
		if err != nil || pool == nil {
			pool = x509.NewCertPool()
		}
		if !pool.AppendCertsFromPEM(pem) {
			return nil, fmt.Errorf("%s: no PEM certificates found", cfg.CAFile)
		}
		tlsCfg.RootCAs = pool
	}
	return &platformClient{cfg: cfg, http: &http.Client{
		Timeout:   20 * time.Second,
		Transport: &http.Transport{TLSClientConfig: tlsCfg, Proxy: http.ProxyFromEnvironment},
	}}, nil
}

func (p *platformClient) endpoint(path string) string {
	return p.cfg.platform().ResolveReference(&url.URL{Path: path}).String()
}

func (p *platformClient) Heartbeat(h Health) (*HeartbeatReply, error) {
	body, _ := json.Marshal(h)
	req, _ := http.NewRequest(http.MethodPost, p.endpoint("/api/wall/nodes/"+url.PathEscape(p.cfg.NodeID)+"/heartbeat"),
		bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+p.cfg.Token)
	resp, err := p.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 300))
		return nil, fmt.Errorf("platform answered %s: %s", resp.Status, bytes.TrimSpace(msg))
	}
	var reply HeartbeatReply
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&reply); err != nil {
		return nil, err
	}
	return &reply, nil
}

// Download fetches a file from the platform (only from the platform) into memory.
func (p *platformClient) Download(path string, limit int64) ([]byte, error) {
	u, err := resolvePage(p.cfg.platform(), path)
	if err != nil {
		return nil, err
	}
	resp, err := p.http.Get(u.String())
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("download %s: %s", path, resp.Status)
	}
	return io.ReadAll(io.LimitReader(resp.Body, limit))
}

func hostname() string {
	h, _ := os.Hostname()
	return h
}

func osName() string { return runtime.GOOS }

func archName() string { return runtime.GOARCH }
