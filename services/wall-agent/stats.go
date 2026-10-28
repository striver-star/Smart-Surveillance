package main

import "sync"

// cpuMeter turns two readings of total and idle CPU time into a percentage.
type cpuMeter struct {
	mu                  sync.Mutex
	lastIdle, lastTotal uint64
}

func (c *cpuMeter) Percent() float64 {
	idle, total, err := cpuTimes()
	if err != nil {
		return -1
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	prevIdle, prevTotal := c.lastIdle, c.lastTotal
	c.lastIdle, c.lastTotal = idle, total
	if prevTotal == 0 || total <= prevTotal || idle < prevIdle {
		return -1
	}
	busy := 1 - float64(idle-prevIdle)/float64(total-prevTotal)
	return float64(int(1000*busy)) / 10
}
