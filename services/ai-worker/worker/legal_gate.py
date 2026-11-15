"""Asks the platform whether face and plate recognition are unlocked (legal review accepted)."""
from __future__ import annotations

import os

import httpx


def check(scopes: list[str], *, api_url: str | None = None, token: str | None = None,
          transport: httpx.BaseTransport | None = None) -> tuple[bool, str]:
    """(allowed, message). Anything other than a clear 'unlocked' answer counts as locked."""
    api_url = api_url or os.environ.get("HSS_API_URL", "http://api:8000")
    token = token if token is not None else os.environ.get("HSS_WORKER_TOKEN", "")
    if not token:
        return False, "HSS_WORKER_TOKEN is not set, so the legal review status can't be checked"
    try:
        with httpx.Client(timeout=5, transport=transport) as http:
            r = http.get(f"{api_url.rstrip('/')}/legal/face-plate/status", headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            st = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        return False, f"the platform could not be asked whether recognition is unlocked ({exc.__class__.__name__})"
    locked = [s for s in scopes if not st.get(s)]
    if locked:
        why = st.get("locked_reason") or "the accepted legal review does not cover it"
        return False, f"{' and '.join(locked)} recognition is locked: {why} (console: Face & plate)"
    return True, f"unlocked by the legal review accepted until {str(st.get('expires_at', ''))[:10]}"
