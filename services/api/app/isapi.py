"""A small Hikvision ISAPI client for the connection test when an NVR is added or edited."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx


class DeviceError(Exception):
    """A plain-language reason the NVR couldn't be read."""


def _strip(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _t(el, path, default=""):
    f = el.find(path) if el is not None else None
    return f.text.strip() if f is not None and f.text else default


def read_nvr(address: str, username: str, password: str, *, scheme: str = "http", timeout: float = 8,
             transport: httpx.BaseTransport | None = None) -> dict:
    """Model, firmware, channels (with online state) and drives. Raises DeviceError with a reason."""
    with httpx.Client(base_url=f"{scheme}://{address}", auth=httpx.DigestAuth(username, password), timeout=timeout,
                      verify=False, transport=transport) as http:
        def get(path):
            r = http.get(path)
            r.raise_for_status()
            return _strip(ET.fromstring(r.text))

        try:
            dev = get("/ISAPI/System/deviceInfo")
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                raise DeviceError("The NVR refused the user name or password (it may also lock the user after several "
                                  "wrong attempts).") from exc
            raise DeviceError(f"The NVR answered HTTP {code}; check that ISAPI is enabled and the address is the NVR's web port.") from exc
        except httpx.ConnectTimeout as exc:
            raise DeviceError("No answer from that address: check the IP, that the server can reach that network, and the port.") from exc
        except httpx.ConnectError as exc:
            raise DeviceError("Connection refused or no route to that address: check the IP and port.") from exc
        except httpx.HTTPError as exc:
            raise DeviceError(f"Couldn't talk to the NVR ({exc.__class__.__name__}).") from exc
        except ET.ParseError as exc:
            raise DeviceError("That address answered, but not like a Hikvision NVR.") from exc

        out = {"name": _t(dev, "deviceName"), "model": _t(dev, "model"), "firmware": _t(dev, "firmwareVersion"),
               "serial": _t(dev, "serialNumber"), "channels": [], "disks": [], "warnings": []}
        try:
            names = {int(_t(c, "id")): (_t(c, "name"), _t(c, "sourceInputPortDescriptor/ipAddress"))
                     for c in get("/ISAPI/ContentMgmt/InputProxy/channels").iter("InputProxyChannel") if _t(c, "id").isdigit()}
            online = {}
            try:
                online = {int(_t(s, "id")): _t(s, "online").lower() == "true"
                          for s in get("/ISAPI/ContentMgmt/InputProxy/channels/status").iter("InputProxyChannelStatus")
                          if _t(s, "id").isdigit()}
            except (httpx.HTTPError, ET.ParseError):
                out["warnings"].append("channel status unavailable")
            for cid in sorted(names):
                n, ip = names[cid]
                out["channels"].append({"id": cid, "name": n or f"Channel {cid}", "ip": ip, "online": online.get(cid)})
        except (httpx.HTTPError, ET.ParseError):
            out["warnings"].append("channel list unavailable: the user may lack the rights to read it")
        try:
            for hdd in get("/ISAPI/ContentMgmt/Storage").iter("hdd"):
                cap = _t(hdd, "capacity")
                out["disks"].append({"name": _t(hdd, "hddName") or f"hdd{_t(hdd, 'id')}", "status": _t(hdd, "status"),
                                     "capacity_gb": round(int(cap) / 1024, 1) if cap.isdigit() else None})
        except (httpx.HTTPError, ET.ParseError):
            out["warnings"].append("drive status unavailable")
        return out
