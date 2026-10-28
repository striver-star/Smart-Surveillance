package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// exitUpdated tells the supervisor (scheduled task or systemd) that a new version is in place.
const exitUpdated = 3

// installUpdate checks the download against the platform's SHA-256 and swaps the executable.
// On Windows a running .exe cannot be overwritten but can be renamed, so the old one is moved
// aside first and deleted on the next start.
func installUpdate(exe string, data []byte, wantSHA256 string) error {
	sum := sha256.Sum256(data)
	if got := hex.EncodeToString(sum[:]); !strings.EqualFold(got, wantSHA256) || wantSHA256 == "" {
		return fmt.Errorf("checksum mismatch: got %s, want %s", got, wantSHA256)
	}
	if len(data) < 1024 {
		return errors.New("download is too small to be the agent")
	}
	dir := filepath.Dir(exe)
	tmp, err := os.CreateTemp(dir, ".hss-wall-agent-*.new")
	if err != nil {
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	tmp.Close()
	if err := os.Chmod(tmp.Name(), 0o755); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	if runtime.GOOS == "windows" {
		old := exe + ".old"
		os.Remove(old)
		if err := os.Rename(exe, old); err != nil {
			os.Remove(tmp.Name())
			return err
		}
	}
	if err := os.Rename(tmp.Name(), exe); err != nil {
		if runtime.GOOS == "windows" {
			_ = os.Rename(exe+".old", exe)
		}
		os.Remove(tmp.Name())
		return err
	}
	return nil
}

func cleanupOldExecutable(exe string) { _ = os.Remove(exe + ".old") }
