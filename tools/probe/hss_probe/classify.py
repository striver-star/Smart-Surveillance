"""Provisional analytics tier and readiness flags for one channel.

The tier is a first guess from what the NVR reports. It is confirmed in PoC step 13 and an
administrator can always override it. "E/N" means a Hikvision device (camera or NVR) offers
smart events for the channel; step 13 tells the two apart. "S" means our server AI is needed.
"""
from __future__ import annotations

SMART_EVENTS = {
    "linedetection", "fielddetection", "regionentrance", "regionexiting",
    "loitering", "group", "rapidmove", "parking", "unattendedbaggage", "attendedbaggage",
    "facedetection", "facesnap", "anpr", "vehicledetection", "humanrecognition",
    "peopledetection", "firedetection", "smokedetection",
}
TAMPER_EVENTS = {"shelteralarm", "tamperdetection"}
RECOGNITION_EVENTS = {"facesnap", "facedetection", "anpr", "vehicledetection"}


def classify_channel(ch: dict) -> dict:
    events = set(ch.get("event_types", []))
    smart = sorted(events & SMART_EVENTS)
    flags: list[str] = []

    sub = ch.get("streams", {}).get("sub", {})
    main = ch.get("streams", {}).get("main", {})
    if not sub:
        flags.append("no sub-stream reported")
    elif sub.get("codec") and sub["codec"].upper() != "H.264":
        flags.append(f"sub-stream is {sub['codec']}: set to H.264 for browser playback")
    if main.get("codec") and "265" not in main["codec"]:
        flags.append(f"main stream is {main['codec']}: H.265 saves NVR storage")
    if ch.get("online") is False:
        flags.append("camera offline")
    if events and not events & TAMPER_EVENTS:
        flags.append("no tamper event: platform image checks needed")

    if ch.get("online") is False:
        tier, reason = "unknown", "camera offline at probe time"
    elif smart:
        tier, reason = "E/N", "device offers smart events: " + ", ".join(smart)
    elif events:
        tier, reason = "S", "only basic events (motion, video loss): server AI needed"
    else:
        tier, reason = "unknown", "no event capabilities returned"

    return {
        "tier": tier,
        "tier_reason": reason,
        "recognition_events": sorted(events & RECOGNITION_EVENTS),
        "flags": flags,
    }
