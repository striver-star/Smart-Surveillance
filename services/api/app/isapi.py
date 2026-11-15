"""A small Hikvision ISAPI client for the connection test when an NVR is added or edited."""
from __future__ import annotations

import re
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


# Event types the platform turns into alerts (Hikvision names, lower case) and their plain names.
WATCHED_EVENTS = {
    "linedetection": "Line crossing", "fielddetection": "Intrusion", "regionentrance": "Region entrance",
    "regionexiting": "Region exiting", "loitering": "Loitering", "unattendedbaggage": "Unattended object",
    "attendedbaggage": "Object removal", "tamperdetection": "Video tampering", "shelteralarm": "Video tampering",
    "videoloss": "Video loss", "scenechangedetection": "Scene change", "vmd": "Motion",
}
DEVICE_EVENTS = {"diskerror": "HDD error", "diskfull": "HDD full", "nicbroken": "Network disconnected",
                 "ipconflict": "IP conflict", "illaccess": "Illegal login"}


def parse_triggers(xml_text: str) -> list[dict]:
    """Event linkage from /ISAPI/Event/triggers (pure, tested): which events notify the surveillance
    centre ("center"), the setting outside software such as HSS needs to receive them."""
    root = _strip(ET.fromstring(xml_text))
    out = []
    for t in root.iter("EventTrigger"):
        etype = _t(t, "eventType").lower()
        # On NVRs, IP camera channels are "dynamic" channels (id like linedetection-D22); prefer that number.
        m = re.search(r"-D(\d+)$", _t(t, "id"))
        ch = _t(t, "dynVideoInputChannelID") or (m.group(1) if m else "") or _t(t, "videoInputChannelID")
        methods = sorted({_t(n, "notificationMethod").lower() for n in t.iter("EventTriggerNotification") if _t(n, "notificationMethod")})
        if etype in WATCHED_EVENTS and ch.isdigit():
            out.append({"channel": int(ch), "event": etype, "name": WATCHED_EVENTS[etype], "center": "center" in methods, "methods": methods})
        elif etype in DEVICE_EVENTS:
            out.append({"channel": None, "event": etype, "name": DEVICE_EVENTS[etype], "center": "center" in methods, "methods": methods})
    return out


def read_event_triggers(address: str, username: str, password: str, *, scheme: str = "http",
                        transport: httpx.BaseTransport | None = None) -> list[dict]:
    with httpx.Client(base_url=f"{scheme}://{address}", auth=httpx.DigestAuth(username, password), timeout=15,
                      verify=False, transport=transport) as http:
        try:
            r = http.get("/ISAPI/Event/triggers")
            r.raise_for_status()
            return parse_triggers(r.text)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise DeviceError("The NVR user may not read event settings: give it 'Remote Parameters Settings' (read).") from exc
            raise DeviceError(f"The NVR answered HTTP {exc.response.status_code} for its event settings.") from exc
        except httpx.HTTPError as exc:
            raise DeviceError(f"Couldn't read the event settings ({exc.__class__.__name__}).") from exc
        except ET.ParseError as exc:
            raise DeviceError("The event settings weren't readable XML.") from exc


def search_body(channel: int, search_id: str) -> str:
    """Ask for the oldest recording of a channel's main stream (track N01). Hikvision spells
    searchResultPostion that way."""
    return (f"<?xml version='1.0' encoding='UTF-8'?><CMSearchDescription><searchID>{search_id}</searchID>"
            f"<trackList><trackID>{channel}01</trackID></trackList><timeSpanList><timeSpan>"
            "<startTime>2000-01-01T00:00:00Z</startTime><endTime>2037-12-31T23:59:59Z</endTime></timeSpan></timeSpanList>"
            "<maxResults>1</maxResults><searchResultPostion>0</searchResultPostion>"
            "<metadataList><metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor></metadataList>"
            "</CMSearchDescription>")


def parse_earliest(xml_text: str) -> str | None:
    """Start time of the first match in a CMSearchResult, as the NVR wrote it (pure, tested)."""
    root = _strip(ET.fromstring(xml_text))
    item = root.find(".//searchMatchItem")
    return _t(item, "timeSpan/startTime") or None if item is not None else None


def earliest_recordings(address: str, username: str, password: str, channels: list[int], *, scheme: str = "http",
                        transport: httpx.BaseTransport | None = None) -> dict[int, str | None]:
    import uuid as _uuid
    out = {}
    with httpx.Client(base_url=f"{scheme}://{address}", auth=httpx.DigestAuth(username, password), timeout=20,
                      verify=False, transport=transport) as http:
        for ch in channels:
            try:
                r = http.post("/ISAPI/ContentMgmt/search", content=search_body(ch, str(_uuid.uuid4()).upper()),
                              headers={"Content-Type": "application/xml"})
                r.raise_for_status()
                out[ch] = parse_earliest(r.text)
            except (httpx.HTTPError, ET.ParseError):
                out[ch] = None
    return out
