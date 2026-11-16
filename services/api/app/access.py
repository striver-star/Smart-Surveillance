"""Per-camera permissions (release 2.0, second batch).

Each user has a camera list: patterns such as "nvr4-*" (all of NVR4) or "nvr1-ch05" (one camera). An empty
list means every camera. Administrators and the CSO always see every camera, whatever their list says.

The list limits everything that shows a camera: live and recorded video (checked at the video gateway,
viewing.py), the camera lists in the console, alerts and their live stream, events, snapshots and clips,
the site map, PTZ and the heat map. A restricted user can't use pages that act on every camera at once
(Event setup).

Roles that only look:
- viewer: live and recorded video, alerts and events read-only, the site map; for their cameras.
- client: an outside client's account: live video (and recordings if allowed) of their cameras only.
Playback can be switched off per user (can_playback).
"""
from __future__ import annotations

import fnmatch
import re

from fastapi import HTTPException

ALL_CAMERAS = ("admin", "cso")
PATTERN = re.compile(r"^[A-Za-z0-9._*?-]{1,64}$")


def patterns(user: dict) -> list[str] | None:
    """The user's camera patterns, or None for every camera (pure, tested)."""
    if user.get("role") in ALL_CAMERAS:
        return None
    pats = [p.strip() for p in (user.get("cameras") or []) if p and p.strip()]
    return pats or None


def allowed(user: dict, camera_id: str | None) -> bool:
    """Whether the user may see this camera (pure, tested). Sub-stream paths count as their camera."""
    pats = patterns(user)
    if pats is None:
        return True
    if not camera_id:
        return False
    cam = camera_id.removesuffix("-sub")
    return any(fnmatch.fnmatchcase(cam.lower(), p.lower()) for p in pats)


def restricted(user: dict) -> bool:
    return patterns(user) is not None


def check(user: dict, camera_id: str | None) -> None:
    if not allowed(user, camera_id):
        raise HTTPException(status_code=403, detail="You don't have access to this camera.")


def sql(user: dict, column: str) -> tuple[str, list]:
    """A WHERE fragment limiting `column` to the user's cameras ('' and [] when unrestricted) (pure, tested).
    Glob patterns become LIKE patterns: * -> %, ? -> _, with % and _ escaped."""
    pats = patterns(user)
    if pats is None:
        return "", []
    likes = []
    for p in pats:
        s = p.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_")
        likes.append(s)
    return f" AND lower({column}) LIKE ANY(%s)", [likes]


def can_play_back(user: dict) -> bool:
    return user.get("role") in ("admin", "cso", "operator", "viewer", "client") and user.get("can_playback", True)


def need_all_cameras(user: dict) -> None:
    if restricted(user):
        raise HTTPException(status_code=403, detail="This page works on every camera; your account is limited to some cameras.")


def clean_patterns(items: list[str]) -> list[str]:
    out = []
    for p in items:
        p = p.strip()
        if not p:
            continue
        if not PATTERN.match(p):
            raise HTTPException(status_code=422, detail=f"'{p[:40]}' isn't a camera or pattern (for example nvr4-* or nvr1-ch05)")
        if p not in out:
            out.append(p)
    return out[:200]
