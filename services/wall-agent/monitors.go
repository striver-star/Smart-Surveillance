package main

import (
	"fmt"
	"sort"
)

// Monitor is one screen, in desktop coordinates.
type Monitor struct {
	Index   int    `json:"index"`
	Name    string `json:"name"`
	X       int    `json:"x"`
	Y       int    `json:"y"`
	Width   int    `json:"width"`
	Height  int    `json:"height"`
	Primary bool   `json:"primary"`
}

func (m Monitor) String() string {
	return fmt.Sprintf("%d %s %dx%d at %d,%d", m.Index, m.Name, m.Width, m.Height, m.X, m.Y)
}

// numberMonitors orders screens left to right, then top to bottom, so monitor 0 is always the
// leftmost TV no matter how the operating system lists them.
func numberMonitors(ms []Monitor) []Monitor {
	sort.SliceStable(ms, func(i, j int) bool {
		if ms[i].X != ms[j].X {
			return ms[i].X < ms[j].X
		}
		return ms[i].Y < ms[j].Y
	})
	for i := range ms {
		ms[i].Index = i
	}
	return ms
}

func sameMonitors(a, b []Monitor) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
