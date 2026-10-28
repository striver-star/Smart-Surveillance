//go:build !linux && !windows

package main

func listMonitors() ([]Monitor, error) {
	return []Monitor{{Index: 0, Name: "default", Width: 1920, Height: 1080, Primary: true}}, nil
}
