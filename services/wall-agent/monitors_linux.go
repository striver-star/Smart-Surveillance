package main

import (
	"os/exec"
	"regexp"
	"strconv"
	"strings"
)

// " 0: +*DP-1 1920/527x1080/296+0+0  DP-1"
var xrandrMonitor = regexp.MustCompile(`^\s*\d+:\s+\+?(\*?)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)`)

func parseXrandrMonitors(out string) []Monitor {
	var ms []Monitor
	for _, line := range strings.Split(out, "\n") {
		m := xrandrMonitor.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		w, _ := strconv.Atoi(m[3])
		h, _ := strconv.Atoi(m[4])
		x, _ := strconv.Atoi(m[5])
		y, _ := strconv.Atoi(m[6])
		ms = append(ms, Monitor{Name: m[2], X: x, Y: y, Width: w, Height: h, Primary: m[1] == "*"})
	}
	return numberMonitors(ms)
}

func listMonitors() ([]Monitor, error) {
	out, err := exec.Command("xrandr", "--listactivemonitors").Output()
	if err != nil {
		return nil, err
	}
	return parseXrandrMonitors(string(out)), nil
}
