package main

import (
	"syscall"
	"unsafe"
)

var (
	user32                  = syscall.NewLazyDLL("user32.dll")
	procEnumDisplayMonitors = user32.NewProc("EnumDisplayMonitors")
	procGetMonitorInfoW     = user32.NewProc("GetMonitorInfoW")
)

type rect struct{ Left, Top, Right, Bottom int32 }

type monitorInfoEx struct {
	CbSize    uint32
	RcMonitor rect
	RcWork    rect
	DwFlags   uint32
	SzDevice  [32]uint16
}

const monitorInfoPrimary = 1

func listMonitors() ([]Monitor, error) {
	var ms []Monitor
	cb := syscall.NewCallback(func(hMonitor, hdc, lprc, lparam uintptr) uintptr {
		var mi monitorInfoEx
		mi.CbSize = uint32(unsafe.Sizeof(mi))
		if r, _, _ := procGetMonitorInfoW.Call(hMonitor, uintptr(unsafe.Pointer(&mi))); r != 0 {
			ms = append(ms, Monitor{
				Name:    syscall.UTF16ToString(mi.SzDevice[:]),
				X:       int(mi.RcMonitor.Left),
				Y:       int(mi.RcMonitor.Top),
				Width:   int(mi.RcMonitor.Right - mi.RcMonitor.Left),
				Height:  int(mi.RcMonitor.Bottom - mi.RcMonitor.Top),
				Primary: mi.DwFlags&monitorInfoPrimary != 0,
			})
		}
		return 1
	})
	if r, _, err := procEnumDisplayMonitors.Call(0, 0, cb, 0); r == 0 {
		return nil, err
	}
	return numberMonitors(ms), nil
}
