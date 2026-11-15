"""Edge service: NVR event streams, device health every minute, and clips for alerts (Phase 3 part B).

Environment:
  HSS_NVRS            NVR addresses, comma separated (e.g. 10.1.3.4,10.1.3.5,10.1.3.6,10.1.3.7)
  HSS_NVR_USER        NVR login used for ISAPI and RTSP (a user with remote view and playback rights)
  HSS_NVR_PASSWORD
  HSS_API_URL         platform API (default http://api:8000)
  HSS_WORKER_TOKEN    the same token the AI workers use
  HSS_TZ              local time zone (default Africa/Lagos); NVR playback uses local time
  HSS_EDGE_IGNORE     Hikvision event types not to forward (default "vmd,motiondetection": plain motion is noise)
  HSS_EDGE_HEALTH_S   seconds between health checks (default 60)
  HSS_EDGE_QUEUE      offline queue folder (default /data/queue)
  HSS_NVR_RTSP_PORT   NVR RTSP port for clips (default 554)
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


def event_loop(nvr: Nvr, platform: Platform, stop: threading.Event, ignore: set[str], pool: ThreadPoolExecutor) -> None:
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
            nvr.stream_events(lambda ev: pool.submit(handle, ev), stop, ignore=ignore)
            backoff = 2
        except (httpx.HTTPError, OSError) as exc:
            log.warning("%s: event stream ended (%s); reconnecting in %ds", nvr.address, exc.__class__.__name__, backoff)
        stop.wait(backoff)
        backoff = min(backoff * 2, 60)


def health_loop(nvrs: list[Nvr], platform: Platform, stop: threading.Event, every: float) -> None:
    while not stop.is_set():
        for n in nvrs:
            h = n.health()
            res = platform.post_health(h)
            if res and res.get("events"):
                log.info("%s: %s", n.address, ", ".join(f"{e['type']} {e['camera_id']}" for e in res["events"]))
        stop.wait(every)


def clip_loop(nvrs: list[Nvr], platform: Platform, stop: threading.Event, tz: ZoneInfo) -> None:
    by_alias = {n.alias: n for n in nvrs}
    while not stop.is_set():
        job = platform.next_clip()
        if not job:
            stop.wait(5)
            continue
        nv_alias, _, ch = job["camera_id"].partition("-ch")
        nvr = by_alias.get(nv_alias)
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


def main() -> None:
    logging.basicConfig(level=os.environ.get("HSS_LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    addresses = [a.strip() for a in os.environ.get("HSS_NVRS", "").split(",") if a.strip()]
    if not addresses:
        raise SystemExit("Set HSS_NVRS to the NVR addresses, e.g. 10.1.3.4,10.1.3.5")
    user, password = os.environ["HSS_NVR_USER"], os.environ["HSS_NVR_PASSWORD"]
    tz = ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))
    ignore = {t.strip().lower() for t in os.environ.get("HSS_EDGE_IGNORE", "vmd,motiondetection").split(",") if t.strip()}
    platform = Platform(os.environ.get("HSS_API_URL", "http://api:8000"), os.environ["HSS_WORKER_TOKEN"],
                        Path(os.environ.get("HSS_EDGE_QUEUE", "/data/queue")))
    nvrs = [Nvr(a, user, password, rtsp_port=int(os.environ.get("HSS_NVR_RTSP_PORT", "554"))) for a in addresses]
    log.info("watching %d NVR(s): %s; ignoring %s", len(nvrs), ", ".join(f"{n.address} ({n.alias})" for n in nvrs), ", ".join(sorted(ignore)) or "nothing")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="snap")
    threads = [threading.Thread(target=event_loop, args=(n, platform, stop, ignore, pool), daemon=True, name=f"events-{n.alias}") for n in nvrs]
    threads += [threading.Thread(target=health_loop, args=(nvrs, platform, stop, float(os.environ.get("HSS_EDGE_HEALTH_S", "60"))), daemon=True),
                threading.Thread(target=clip_loop, args=(nvrs, platform, stop, tz), daemon=True),
                threading.Thread(target=queue_loop, args=(platform, stop), daemon=True)]
    for t in threads:
        t.start()
    while not stop.is_set():
        stop.wait(1)
    pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
