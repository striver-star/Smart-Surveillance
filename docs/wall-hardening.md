# Wall PC and TV hardening guide

For the wall PCs (Core i5, 16 GB, Windows) and the 55-inch Hisense TVs. Goal: the wall comes back on
its own after a power cut, never shows a desktop, pop-up or sleep screen, and can't be misused.

## Hisense TVs

Menu names differ by model and firmware (VIDAA or Android TV); look for the closest match.

1. **Picture size**: Settings › Picture › Aspect ratio **Just Scan** / **Dot by dot** (no overscan, so
   the grid's edges and camera names aren't cut off). Name the HDMI input **PC** if the TV offers it,
   which also turns off extra processing.
2. **Picture mode**: Standard or PC; turn off motion smoothing, noise reduction and dynamic contrast.
   Backlight about 70%, which also lengthens panel life.
3. **Power**: turn off *Auto power off*, *No signal power off*, *Sleep timer* and *Eco* / *Energy
   saving* screen-off. Set *Power on mode* / *After power failure* to **On** (or *Last state*), and the
   input at power on to the PC's HDMI port.
4. **HDMI-CEC** (Anynet / *CEC control*): **off**, so the PC can't switch the TV off or change input.
5. **Updates and apps**: turn off automatic software updates and any start-up app or home screen; turn
   off voice assistants. Keep the remote control locked away.
6. If a TV has a *Hotel* or *Commercial* mode, use it to lock the menu and the input.

## Windows wall PCs

**Account and start-up**
1. A local **standard** (not administrator) user, for example `wall`, used only for the wall. Turn on
   automatic sign-in for it (`netplwiz`, or Sysinternals Autologon, which stores the password encrypted).
2. Install the Wall Agent with the installer from the server (docs/task-22-wall-agent.md); it starts at
   sign-in and opens one full-screen browser per TV.
3. BIOS: **Restore on AC power loss: Power On**; turn on Wake on LAN for remote restarts.

**Never sleep, never pop up**
4. Power plan: *High performance*; screen off **Never**, sleep **Never**, hibernate off, USB selective
   suspend off.
5. Screen saver **None**; turn off the lock screen and *Require sign-in after sleep*.
6. Notifications off for the wall user; *Do not disturb* on; turn off *Tips*, *Suggestions* and the
   *Welcome experience*.
7. Windows Update: set *Active hours* to the wall's working hours and allow restarts only in a nightly
   window (Group Policy *Configure Automatic Updates*: scheduled install at 03:00). The agent reopens
   the wall after the restart.

**Video performance**
8. Install the Intel graphics driver from Intel (not the Windows Update default); check that hardware
   video decoding is on in the browser (`edge://gpu` or `chrome://gpu`: *Video Decode: Hardware
   accelerated*).
9. Each TV at its native 1920 × 1080 (or 3840 × 2160 if the PC handles it), scaling 100%, 60 Hz.
10. Wired network only, on the camera VLAN or a route to the server; no Wi-Fi.

**Lock it down**
11. Browser policies for the wall user (Group Policy or registry for Edge or Chrome): turn off the
    password manager, translation prompts, sign-in, sync, the *Restore pages* bubble, extensions and
    developer tools; allow autoplay for the server's address.
12. Trust the server's certificate authority on the PC (docs/console.md) so the wall opens without a
    certificate warning.
13. Windows Firewall on; allow inbound only what remote support needs. Turn off Remote Desktop unless it
    is used, and then only from the IT VLAN.
14. BitLocker on the system drive; BIOS password set; boot from USB disabled.
15. Keep a keyboard out of reach of operators; the wall is controlled from the console.

## Check after setting up

- Pull the power from the PC and TV together; when power returns, both start and the wall shows within
  3 minutes with no clicks.
- Unplug the network for 2 minutes and reconnect: every tile comes back on its own.
- In the console, Video walls shows the PC online and each TV "n/n playing".
