package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

// Google Chrome and Microsoft Edge are deliberately not on these lists (Section 19).
var chromiumCandidates = map[string][]string{
	"windows": {
		`%ProgramFiles%\Chromium\Application\chrome.exe`,
		`%LOCALAPPDATA%\Chromium\Application\chrome.exe`,
		`%ProgramFiles(x86)%\Chromium\Application\chrome.exe`,
	},
	"linux": {"/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium"},
}
var firefoxCandidates = map[string][]string{
	"windows": {`%ProgramFiles%\Mozilla Firefox\firefox.exe`},
	"linux":   {"/usr/bin/firefox", "/snap/bin/firefox"},
}

func findBrowser(configured string) (string, error) {
	if configured != "" {
		if _, err := os.Stat(configured); err != nil {
			return "", fmt.Errorf("browser %q: %w", configured, err)
		}
		return configured, nil
	}
	for _, list := range [][]string{chromiumCandidates[runtime.GOOS], firefoxCandidates[runtime.GOOS]} {
		for _, p := range list {
			p = os.ExpandEnv(strings.NewReplacer("%ProgramFiles%", "${ProgramFiles}",
				"%LOCALAPPDATA%", "${LOCALAPPDATA}", "%ProgramFiles(x86)%", "${ProgramFiles(x86)}").Replace(p))
			if _, err := os.Stat(p); err == nil {
				return p, nil
			}
		}
	}
	return "", errors.New("no Chromium or Firefox found; set \"browser\" in the config")
}

func isFirefox(path string) bool {
	return strings.Contains(strings.ToLower(filepath.Base(path)), "firefox")
}

// browserCommand builds the kiosk command for one monitor. Each monitor gets its own profile
// directory so the windows are independent processes that can be restarted one at a time.
func browserCommand(browser string, m Monitor, pageURL, profileDir string, extra []string) *exec.Cmd {
	var args []string
	if isFirefox(browser) {
		// Firefox cannot be placed on a chosen monitor from the command line; use it for single-screen PCs.
		args = []string{"--kiosk", "--new-instance", "--profile", profileDir}
	} else {
		args = []string{
			"--kiosk",
			"--user-data-dir=" + profileDir,
			"--window-position=" + strconv.Itoa(m.X) + "," + strconv.Itoa(m.Y),
			"--window-size=" + strconv.Itoa(m.Width) + "," + strconv.Itoa(m.Height),
			"--no-first-run",
			"--no-default-browser-check",
			"--noerrdialogs",
			"--disable-session-crashed-bubble",
			"--disable-infobars",
			"--hide-crash-restore-bubble",
			"--autoplay-policy=no-user-gesture-required",
			"--disable-features=Translate,MediaRouter",
			"--disable-background-timer-throttling",
			"--disable-renderer-backgrounding",
			"--disable-backgrounding-occluded-windows",
			"--check-for-update-interval=31536000",
		}
		if runtime.GOOS == "linux" {
			args = append(args, "--password-store=basic")
		}
	}
	args = append(args, extra...)
	args = append(args, pageURL)
	cmd := exec.Command(browser, args...)
	prepareProcess(cmd)
	return cmd
}
