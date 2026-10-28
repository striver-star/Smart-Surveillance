package main

import (
	"encoding/json"
	"io"
	"log"
	"net"
	"net/http"
	"strconv"
	"strings"
)

// localServer receives heartbeats from the wall pages on 127.0.0.1 only. The pages come from the
// platform's own origin, so only that origin is allowed to call it.
func localServer(cfg *Config, sv *Supervisor, status func() any) *http.Server {
	origin := strings.TrimSuffix(cfg.platform().Scheme+"://"+cfg.platform().Host, "/")
	mux := http.NewServeMux()
	mux.HandleFunc("/heartbeat", func(w http.ResponseWriter, r *http.Request) {
		if o := r.Header.Get("Origin"); o != "" {
			if o != origin {
				http.Error(w, "origin not allowed", http.StatusForbidden)
				return
			}
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
		}
		if r.Method == http.MethodOptions {
			// CORS and Private Network Access preflight from the https platform page.
			w.Header().Set("Access-Control-Allow-Methods", "POST")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
			w.Header().Set("Access-Control-Allow-Private-Network", "true")
			w.WriteHeader(http.StatusNoContent)
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", http.StatusMethodNotAllowed)
			return
		}
		monitor, err := strconv.Atoi(r.URL.Query().Get("monitor"))
		if err != nil {
			http.Error(w, "monitor missing", http.StatusBadRequest)
			return
		}
		body, err := io.ReadAll(io.LimitReader(r.Body, 64<<10))
		if err != nil || (len(body) > 0 && !json.Valid(body)) {
			http.Error(w, "body must be JSON", http.StatusBadRequest)
			return
		}
		if len(body) == 0 {
			body = []byte("{}")
		}
		if !sv.PageHeartbeat(monitor, body) {
			http.Error(w, "unknown monitor", http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(status())
	})
	return &http.Server{Addr: net.JoinHostPort("127.0.0.1", strconv.Itoa(cfg.LocalPort)), Handler: mux}
}

func serveLocal(srv *http.Server) {
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Printf("local heartbeat server: %v", err)
	}
}
