package main

import "testing"

func TestParseXrandrNumbersLeftToRight(t *testing.T) {
	out := "Monitors: 2\n 0: +*HDMI-2 1920/1210x1080/680+1920+0  HDMI-2\n 1: +HDMI-1 1920/1210x1080/680+0+0  HDMI-1\n"
	ms := parseXrandrMonitors(out)
	if len(ms) != 2 || ms[0].Name != "HDMI-1" || ms[0].Index != 0 || ms[1].X != 1920 || !ms[1].Primary {
		t.Fatalf("got %+v", ms)
	}
}
