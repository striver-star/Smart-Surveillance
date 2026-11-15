"""Talking to the platform API, with an on-disk queue so no event is lost while the API is down."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

import httpx

log = logging.getLogger("edge.platform")
MAX_QUEUED = 10_000


class Platform:
    def __init__(self, base_url: str, token: str, queue_dir: Path, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                                 timeout=30, transport=transport)
        self.queue = queue_dir
        self.queue.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    # ---- events (queued when the API can't take them)
    def post_event(self, event: dict) -> str:
        """'sent', 'queued' or 'rejected'."""
        if self.queued_count():
            self._enqueue(event)              # keep order: older events go first
            return "queued"
        return self._send(event, queue_on_failure=True)

    def _send(self, event: dict, *, queue_on_failure: bool) -> str:
        try:
            r = self.http.post("/events", json=event)
        except httpx.HTTPError as exc:
            log.warning("API not reachable (%s); queueing", exc.__class__.__name__)
            if queue_on_failure:
                self._enqueue(event)
            return "queued"
        if r.status_code >= 500:
            if queue_on_failure:
                self._enqueue(event)
            return "queued"
        if r.status_code >= 400:
            log.error("API rejected an event (%s): %s", r.status_code, r.text[:200])
            return "rejected"
        return "sent"

    def _enqueue(self, event: dict) -> None:
        with self.lock:
            files = sorted(self.queue.glob("*.json"))
            if len(files) >= MAX_QUEUED:
                files[0].unlink(missing_ok=True)
                log.error("offline queue full; dropped the oldest event")
            name = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}.json"
            tmp = self.queue / (name + ".tmp")
            tmp.write_text(json.dumps(event))
            tmp.rename(self.queue / name)

    def queued_count(self) -> int:
        return len(list(self.queue.glob("*.json")))

    def flush(self, limit: int = 200) -> int:
        """Send queued events, oldest first; stop at the first failure. Returns how many were sent."""
        sent = 0
        with self.lock:
            files = sorted(self.queue.glob("*.json"))[:limit]
        for f in files:
            try:
                event = json.loads(f.read_text())
            except (OSError, ValueError):
                f.unlink(missing_ok=True)
                continue
            result = self._send(event, queue_on_failure=False)
            if result == "queued":
                break
            f.unlink(missing_ok=True)          # sent, or rejected for good (logged)
            sent += result == "sent"
        if sent:
            log.info("sent %d queued event(s); %d still queued", sent, self.queued_count())
        return sent

    # ---- device health
    def post_health(self, health: dict) -> dict | None:
        try:
            r = self.http.post("/devices/health", json=health)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            log.warning("health not delivered: %s", exc)
            return None

    # ---- clips
    def next_clip(self) -> dict | None:
        try:
            r = self.http.get("/clips/next")
            r.raise_for_status()
            return r.json().get("job")
        except httpx.HTTPError:
            return None

    def upload_clip(self, clip_id: str, data: bytes) -> bool:
        try:
            r = self.http.put(f"/clips/{clip_id}", content=data, headers={"Content-Type": "video/mp4"}, timeout=120)
            r.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("clip upload failed: %s", exc)
            return False

    def fail_clip(self, clip_id: str, detail: str) -> None:
        try:
            self.http.post(f"/clips/{clip_id}/fail", json={"detail": detail[:500]})
        except httpx.HTTPError:
            pass
