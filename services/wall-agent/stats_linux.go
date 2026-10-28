package main

import (
	"bufio"
	"os"
	"strconv"
	"strings"
)

func cpuTimes() (idle, total uint64, err error) {
	f, err := os.Open("/proc/stat")
	if err != nil {
		return 0, 0, err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Scan()
	fields := strings.Fields(sc.Text())[1:]
	for i, v := range fields {
		n, _ := strconv.ParseUint(v, 10, 64)
		total += n
		if i == 3 || i == 4 { // idle, iowait
			idle += n
		}
	}
	return idle, total, nil
}

func memoryUsage() (usedPercent float64, totalMB uint64) {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return -1, 0
	}
	defer f.Close()
	vals := map[string]uint64{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		parts := strings.Fields(sc.Text())
		if len(parts) >= 2 {
			n, _ := strconv.ParseUint(parts[1], 10, 64)
			vals[strings.TrimSuffix(parts[0], ":")] = n
		}
	}
	if vals["MemTotal"] == 0 {
		return -1, 0
	}
	used := vals["MemTotal"] - vals["MemAvailable"]
	return float64(int(1000*float64(used)/float64(vals["MemTotal"]))) / 10, vals["MemTotal"] / 1024
}
