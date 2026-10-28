package main

import (
	"os/exec"
	"strconv"
	"syscall"
)

const createNoWindow = 0x08000000

func prepareProcess(cmd *exec.Cmd) {}

// killTree stops the browser and every helper process it started.
func killTree(cmd *exec.Cmd) {
	if cmd.Process == nil {
		return
	}
	kill := exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(cmd.Process.Pid))
	kill.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
	if kill.Run() != nil {
		_ = cmd.Process.Kill()
	}
}
