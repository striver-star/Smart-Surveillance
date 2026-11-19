"""Edge service: NVR event streams, device health every minute, and clips for alerts (Phase 3 part B).

NVRs come from the console (Devices, Add NVR), checked every minute, so adding, editing or removing an
NVR there takes effect without a restart. Only while the console has no NVRs registered, the .env list
below is used instead.

Environment:
  HSS_NVRS            fallback NVR addresses, comma separated (e.g. 10.1.3.4,10.1.3.5,10.1.3.6,10.1.3.7)
  HSS_NVR_USER        fallback NVR login used for ISAPI and RTSP (a user with remote view and playback rights)
  HSS_NVR_PASSWORD
  HSS_API_URL         platform API (default http://api:8000)
  HSS_WORKER_TOKEN    the same token the AI workers use
  HSS_TZ              local time zone (default Africa/Lagos); NVR playback uses local time
  HSS_EDGE_IGNORE     Hikvision event types not to forward (default "vmd,motiondetection": plain motion is noise);
                      cameras chosen for smart motion in the console (Event setup) still send motion when the
                      camera says it was a person or vehicle
  HSS_EDGE_HEALTH_S   seconds between health checks (default 60)
  HSS_EDGE_QUEUE      offline queue folder (default /data/queue)
  HSS_NVR_RTSP_PORT   fallback NVR RTSP port for clips (default 554)
  HSS_EDGE_REFRESH_S  seconds between checks of the console's NVR list (default 60)
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .nvr import Nvr, alias
from .platform import Platform

log = logging.getLogger("edge")


def event_loop(nvr: Nvr, platform: Platform, stop: threading.Event, ignore: set[str], pool: ThreadPoolExecutor,
               smart_motion=lambda: set()) -> None:
    def handle(ev: dict) -> None:
        ch = ev.pop("_channel")
        if not ev.get("snapshot_jpeg_b64"):
            pic = nvr.snapshot(ch)
            if pic:
                import base64
                ev["snapshot_jpeg_b64"] = base64.b64encode(pic).decode()
        log.info("%s %s (%s)", ev["camera_id"], ev["type"], platform.post_event(ev))

    backoff = 2
    while not stop.is_set():
        try:
            nvr.stream_events(lambda ev: pool.submit(handle, ev), stop, ignore=ignore, smart_motion=smart_motion)
            backoff = 2
        except (httpx.HTTPError, OSError) as exc:
            log.warning("%s: event stream ended (%s); reconnecting in %ds", nvr.address, exc.__class__.__name__, backoff)
        stop.wait(backoff)
        backoff = min(backoff * 2, 60)


def spec_key(spec: dict) -> tuple:
    return (spec["address"], spec.get("alias") or alias(spec["address"]), spec["username"], spec["password"],
            spec.get("scheme", "http"), int(spec.get("rtsp_port", 554)))


def choose_specs(registry: list[dict] | None, env_specs: list[dict], running: list[dict] | None) -> tuple[list[dict], str]:
    """Which NVRs to watch (pure function, tested): the console's list when it has any; the .env list when the
    console has none; and, when the API can't be asked, whatever is already running (or .env at start-up)."""
    if registry is None:
        return (running, "unchanged (API not answering)") if running is not None else (env_specs, ".env (API not answering)")
    if registry:
        return registry, "console"
    return env_specs, ".env (no NVRs added in the console yet)"


class Fleet:
    """The NVRs being watched. Each has its own event thread; health and clips use the current list."""

    def __init__(self, platform: Platform, stop: threading.Event, ignore: set[str], pool: ThreadPoolExecutor):
        self.platform, self.stop, self.ignore, self.pool = platform, stop, ignore, pool
        self.running: dict[tuple, tuple[Nvr, threading.Event, dict]] = {}
        self.lock = threading.Lock()
        self.source = ""
        self.smart_motion: set[str] = set()          # cameras whose person/vehicle motion is forwarded

    def current(self) -> list[Nvr]:
        with self.lock:
            return [n for n, _, _ in self.running.values()]

    def apply(self, specs: list[dict], source: str) -> None:
        want = {spec_key(s): s for s in specs}
        with self.lock:
            for key in [k for k in self.running if k not in want]:
                nvr, own_stop, _ = self.running.pop(key)
                own_stop.set()
                log.info("stopped watching %s (%s)", nvr.address, nvr.alias)
            for key, spec in want.items():
                if key in self.running:
                    continue
                nvr = Nvr(spec["address"], spec["username"], spec["password"], scheme=spec.get("scheme", "http"),
                          rtsp_port=int(spec.get("rtsp_port", 554)), alias_name=spec.get("alias"))
                own_stop = threading.Event()
                threading.Thread(target=event_loop, args=(nvr, self.platform, _either(self.stop, own_stop), self.ignore, self.pool,
                                                         lambda: self.smart_motion),
                                 daemon=True, name=f"events-{nvr.alias}").start()
                self.running[key] = (nvr, own_stop, spec)
                log.info("watching %s (%s)", nvr.address, nvr.alias)
        if source != self.source and not source.startswith("unchanged"):
            log.info("NVR list from %s: %d NVR(s)", source, len(want))
            self.source = source

    def set_smart_motion(self, cams: list[str] | None) -> None:
        if cams is None:                             # API not answering: keep the list we have
            return
        new = set(cams)
        if new != self.smart_motion:
            log.info("smart motion (person/vehicle) from: %s", ", ".join(sorted(new)) or "no cameras")
            self.smart_motion = new

    def specs(self) -> list[dict] | None:
        with self.lock:
            return [s for _, _, s in self.running.values()] if self.running or self.source else None


class _either(threading.Event):
    """Set when either of two events is set (the service stopping, or this NVR being removed)."""

    def __init__(self, a: threading.Event, b: threading.Event):
        super().__init__()
        self.a, self.b = a, b

    def is_set(self) -> bool:
        return self.a.is_set() or self.b.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        end = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            left = 0.5 if end is None else min(0.5, end - time.monotonic())
            if left <= 0:
                break
            self.a.wait(left)
        return self.is_set()


def health_loop(fleet: Fleet, platform: Platform, stop: threading.Event, every: float) -> None:
    while not stop.is_set():
        for n in fleet.current():
            h = n.health()
            res = platform.post_health(h)
            if res and res.get("events"):
                log.info("%s: %s", n.address, ", ".join(f"{e['type']} {e['camera_id']}" for e in res["events"]))
        stop.wait(every)


def clip_loop(fleet: Fleet, platform: Platform, stop: threading.Event, tz: ZoneInfo) -> None:
    while not stop.is_set():
        job = platform.next_clip()
        if not job:
            stop.wait(5)
            continue
        nv_alias, _, ch = job["camera_id"].partition("-ch")
        nvr = {n.alias: n for n in fleet.current()}.get(nv_alias)
        if not nvr or not ch.isdigit():
            platform.fail_clip(job["id"], f"no NVR configured for {job['camera_id']}")
            continue
        try:
            data = nvr.cut_clip(int(ch), datetime.fromisoformat(job["starts_at"]), datetime.fromisoformat(job["ends_at"]), tz)
            ok = platform.upload_clip(job["id"], data)
            log.info("clip %s for %s: %s (%d KB)", job["id"][:8], job["camera_id"], "uploaded" if ok else "upload failed", len(data) // 1024)
            if not ok:
                platform.fail_clip(job["id"], "upload to the platform failed")
        except Exception as exc:  # report and move on; the API retries later
            log.warning("clip %s for %s failed: %s", job["id"][:8], job["camera_id"], exc)
            platform.fail_clip(job["id"], str(exc))


def queue_loop(platform: Platform, stop: threading.Event) -> None:
    while not stop.is_set():
        if platform.queued_count():
            platform.flush()
        stop.wait(10)


def env_specs() -> list[dict]:
    addresses = [a.strip() for a in os.environ.get("HSS_NVRS", "").split(",") if a.strip()]
    user, password = os.environ.get("HSS_NVR_USER", ""), os.environ.get("HSS_NVR_PASSWORD", "")
    if addresses and not (user and password):
        log.warning("HSS_NVRS is set but HSS_NVR_USER or HSS_NVR_PASSWORD is empty; the .env list is not used")
        return []
    port = int(os.environ.get("HSS_NVR_RTSP_PORT", "554"))
    return [{"address": a, "alias": alias(a), "username": user, "password": password, "rtsp_port": port} for a in addresses]


def main() -> None:
    logging.basicConfig(level=os.environ.get("HSS_LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    tz = ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))
    ignore = {t.strip().lower() for t in os.environ.get("HSS_EDGE_IGNORE", "vmd,motiondetection").split(",") if t.strip()}
    platform = Platform(os.environ.get("HSS_API_URL", "http://api:8000"), os.environ["HSS_WORKER_TOKEN"],
                        Path(os.environ.get("HSS_EDGE_QUEUE", "/data/queue")))
    fallback = env_specs()
    log.info("ignoring event types: %s", ", ".join(sorted(ignore)) or "nothing")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="snap")
    fleet = Fleet(platform, stop, ignore, pool)
    fleet.apply(*choose_specs(platform.nvr_list(), fallback, None))
    fleet.set_smart_motion(platform.smart_motion())
    if not fleet.current():
        log.warning("no NVRs to watch yet: add one in the console (Devices, Add NVR); checking again every minute")
    threads = [threading.Thread(target=health_loop, args=(fleet, platform, stop, float(os.environ.get("HSS_EDGE_HEALTH_S", "60"))), daemon=True),
               threading.Thread(target=clip_loop, args=(fleet, platform, stop, tz), daemon=True),
               threading.Thread(target=queue_loop, args=(platform, stop), daemon=True)]
    for t in threads:
        t.start()
    refresh = float(os.environ.get("HSS_EDGE_REFRESH_S", "60"))
    while not stop.wait(refresh):
        fleet.apply(*choose_specs(platform.nvr_list(), fallback, fleet.specs()))
        fleet.set_smart_motion(platform.smart_motion())
    pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
