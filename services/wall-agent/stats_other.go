//go:build !linux && !windows

package main

import "errors"

func cpuTimes() (idle, total uint64, err error) { return 0, 0, errors.New("not supported") }

func memoryUsage() (usedPercent float64, totalMB uint64) { return -1, 0 }
