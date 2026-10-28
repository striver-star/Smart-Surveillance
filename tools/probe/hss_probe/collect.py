"""Collect an inventory of one NVR: device, storage, channels, streams and event capabilities."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone

from .classify import classify_channel
from .isapi import IsapiClient

# Read-only endpoints queried for every NVR. Raw responses are saved for later review.
ENDPOINTS = {
    "device_info": "/ISAPI/System/deviceInfo",
    "time": "/ISAPI/System/time",
    "storage": "/ISAPI/ContentMgmt/Storage",
    "channels": "/ISAPI/ContentMgmt/InputProxy/channels",
    "channel_status": "/ISAPI/ContentMgmt/InputProxy/channels/status",
    "streams": "/ISAPI/ContentMgmt/StreamingProxy/channels",
    "event_caps": "/ISAPI/Event/capabilities",
    "smart_caps": "/ISAPI/Smart/capabilities",
}


def _text(el: ET.Element | None, path: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else default


def _int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_device(root: ET.Element | None) -> dict:
    return {
        "name": _text(root, "deviceName"),
        "model": _text(root, "model"),
        "serial": _text(root, "serialNumber"),
        "mac": _text(root, "macAddress"),
        "firmware": _text(root, "firmwareVersion"),
        "firmware_date": _text(root, "firmwareReleasedDate"),
        "device_type": _text(root, "deviceType"),
    }


def parse_time(root: ET.Element | None) -> dict:
    return {
        "mode": _text(root, "timeMode"),
        "local_time": _text(root, "localTime"),
        "timezone": _text(root, "timeZone"),
    }


def parse_storage(root: ET.Element | None) -> list[dict]:
    disks = []
    if root is None:
        return disks
    for hdd in root.iter("hdd"):
        cap_mb = _int(_text(hdd, "capacity"))
        free_mb = _int(_text(hdd, "freeSpace"))
        disks.append({
            "id": _text(hdd, "id"),
            "name": _text(hdd, "hddName"),
            "type": _text(hdd, "hddType"),
            "status": _text(hdd, "status"),
            "property": _text(hdd, "property"),
            "capacity_gb": round(cap_mb / 1024, 1) if cap_mb is not None else None,
            "free_gb": round(free_mb / 1024, 1) if free_mb is not None else None,
        })
    return disks


def parse_streams(root: ET.Element | None) -> dict[int, dict[str, dict]]:
    """Map channel number -> {'main': {...}, 'sub': {...}} from StreamingProxy ids like 101, 102."""
    result: dict[int, dict[str, dict]] = {}
    if root is None:
        return result
    for sc in root.iter("StreamingChannel"):
        sid = _int(_text(sc, "id"))
        if sid is None:
            continue
        channel, stream_no = divmod(sid, 100)
        kind = {1: "main", 2: "sub"}.get(stream_no, f"stream{stream_no}")
        video = sc.find("Video")
        rc = _text(video, "videoQualityControlType").upper()
        cbr = _int(_text(video, "constantBitRate"))
        vbr_cap = _int(_text(video, "vbrUpperCap"))
        fps_raw = _int(_text(video, "maxFrameRate"))
        result.setdefault(channel, {})[kind] = {
            "codec": _text(video, "videoCodecType"),
            "width": _int(_text(video, "videoResolutionWidth")),
            "height": _int(_text(video, "videoResolutionHeight")),
            "fps": fps_raw / 100 if fps_raw and fps_raw > 100 else fps_raw,
            "rate_control": rc,
            "bitrate_kbps": cbr if rc == "CBR" else (vbr_cap or cbr),
            "smart_codec": _text(video, "SmartCodec/enabled"),
        }
    return result


def parse_channels(channels: ET.Element | None, status: ET.Element | None) -> dict[int, dict]:
    result: dict[int, dict] = {}
    if channels is not None:
        for ch in channels.iter("InputProxyChannel"):
            cid = _int(_text(ch, "id"))
            if cid is None:
                continue
            src = ch.find("sourceInputPortDescriptor")
            result[cid] = {
                "id": cid,
                "name": _text(ch, "name"),
                "camera_ip": _text(src, "ipAddress"),
                "protocol": _text(src, "proxyProtocol"),
                "source_port": _text(src, "srcInputPort"),
                "online": None,
                "detect_result": "",
            }
    if status is not None:
        for st in status.iter("InputProxyChannelStatus"):
            cid = _int(_text(st, "id"))
            if cid is None:
                continue
            entry = result.setdefault(cid, {"id": cid, "name": "", "camera_ip": "", "protocol": "",
                                            "source_port": ""})
            entry["online"] = _text(st, "online").lower() == "true"
            entry["detect_result"] = _text(st, "chanDetectResult")
    return result


def parse_event_types(root: ET.Element | None) -> list[str]:
    """Event types from ChannelEventCap/eventType@opt, lower-cased."""
    if root is None:
        return []
    el = root.find("eventType")
    opt = el.get("opt", "") if el is not None else ""
    return sorted({t.strip().lower() for t in opt.split(",") if t.strip()})


def parse_supported_flags(root: ET.Element | None) -> list[str]:
    """Names of capability elements whose value is 'true' (for example isSupportLineDetection)."""
    if root is None:
        return []
    return sorted({el.tag for el in root.iter() if (el.text or "").strip().lower() == "true"})


def collect(client: IsapiClient, address: str, *, listen_seconds: float = 0) -> tuple[dict, dict[str, str]]:
    """Return (inventory, raw_responses). raw_responses maps a file name to the response body."""
    raw: dict[str, str] = {}
    endpoint_status: dict[str, int] = {}
    roots: dict[str, ET.Element | None] = {}
    for key, path in ENDPOINTS.items():
        resp = client.get(path)
        raw[f"{key}.xml"] = resp.text
        endpoint_status[path] = resp.status
        roots[key] = resp.xml()

    channels = parse_channels(roots["channels"], roots["channel_status"])
    streams = parse_streams(roots["streams"])

    for cid, ch in channels.items():
        resp = client.get(f"/ISAPI/Event/channels/{cid}/capabilities")
        raw[f"channel_{cid:02d}_event_caps.xml"] = resp.text
        endpoint_status[resp.path] = resp.status
        ch["event_types"] = parse_event_types(resp.xml())
        ch["streams"] = streams.get(cid, {})
        ch.update(classify_channel(ch))

    inventory = {
        "address": address,
        "probed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": parse_device(roots["device_info"]),
        "time": parse_time(roots["time"]),
        "storage": parse_storage(roots["storage"]),
        "nvr_event_types": parse_event_types(roots["event_caps"]),
        "nvr_smart_flags": parse_supported_flags(roots["smart_caps"]),
        "channels": [channels[c] for c in sorted(channels)],
        "endpoint_status": endpoint_status,
    }

    if listen_seconds > 0:
        counts: Counter[str] = Counter()
        for i, block in enumerate(client.stream_events(listen_seconds)):
            raw[f"event_{i:04d}.xml"] = block
            etype = re.search(r"<eventType>([^<]+)</eventType>", block)
            chan = re.search(r"<(?:channelID|dynChannelID)>(\d+)</", block)
            counts[f"{etype.group(1) if etype else '?'} @ ch{chan.group(1) if chan else '?'}"] += 1
        inventory["events_heard"] = {"seconds": listen_seconds, "counts": dict(counts)}

    return inventory, raw
