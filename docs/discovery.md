# Network discovery for new sites

Release 2.0, third batch. Find the Hikvision NVRs and cameras on a site's network during set-up, instead of typing
addresses from a spreadsheet.

## In the console: Devices › Find devices (administrators)

1. The ranges start with the server's own network and the networks of NVRs already added (`HSS_SERVER_IP` in
   `.env` gives the server's address). Add others: `10.1.3.0/24, 10.1.4.10-60, 10.1.5.7`.
2. **Scan** checks every address for the ports Hikvision devices answer on (80, 443, 8000, 554); a /24 takes a few
   seconds. Devices that answer are recognised **without logging in**, from their web server's name, login realm
   and activation page:

   | Shown as | Means |
   |---|---|
   | NVR / Camera, with the model when the device gives it | A Hikvision device |
   | **added as nvr4** | Already in Devices |
   | **not activated** | Brand new or reset: activate it with a strong password (Hikvision SADP or its web page) before use |
   | Other camera (RTSP) | Answers on RTSP but isn't recognised as Hikvision (another make, or the web server is off) |

3. **Identify** logs in once with a user and password you type (not stored) and shows the model, serial, firmware,
   channels (online) and drives. Several wrong passwords can lock the user on the device.
4. **Add as NVR** opens the usual Add NVR form with the address filled in. Use a dedicated NVR user, not admin.

Cameras plugged into an NVR's own PoE ports sit on the NVR's internal network (often 192.168.254.x) and can't be
seen from the LAN; they appear under the NVR once it's added.

Limits: private addresses only (10.x, 172.16 to 31.x, 192.168.x, 169.254.x), at most 4,096 addresses (a /20) per
scan, one scan at a time. Every scan and every Identify is in the audit log. Ask the site's IT before scanning a
network you don't manage: some firewalls flag scans.

## On the server: tools/discovery/hss-sadp.py

Hikvision's own discovery (SADP, multicast on UDP 37020) finds devices even on default or unknown addresses (for
example a new camera on 192.0.0.64), with model, serial, MAC, firmware and activation state. Multicast doesn't
cross routers or reach inside Docker, so run it on the server itself, or on a laptop on the camera VLAN:

```bash
python3 tools/discovery/hss-sadp.py
```
```bash
python3 tools/discovery/hss-sadp.py --interface 10.1.3.20 --json
```

It only reads; it never changes or activates a device.
