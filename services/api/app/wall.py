"""Wall Agent endpoints: heartbeats with health, screen layouts and agent updates."""
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Path as PathParam
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from .db import connect

router = APIRouter(prefix="/wall")
NODE_ID = PathParam(pattern=r"^[A-Za-z0-9._-]{1,64}$")
ONLINE_SECONDS = 60


def _check(env: str, authorization: str | None) -> None:
    expected = os.environ.get(env, "")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="invalid token")


def wall_token(authorization: str | None = Header(default=None)) -> None:
    _check("HSS_WALL_TOKEN", authorization)


def admin_token(authorization: str | None = Header(default=None)) -> None:
    # Stand-in until Phase 1 brings users, roles and sign-in.
    _check("HSS_ADMIN_TOKEN", authorization)


class Heartbeat(BaseModel):
    hostname: str = Field(default="", max_length=255)
    agent_version: str = Field(default="", max_length=50)
    os: str = Field(default="", max_length=20)
    arch: str = Field(default="", max_length=20)
    model_config = {"extra": "allow"}


class MonitorLayout(BaseModel):
    monitor: int = Field(ge=0, le=15)
    path: str = Field(min_length=1, max_length=2000)

    @field_validator("path")
    @classmethod
    def platform_path_only(cls, v: str) -> str:
        parts = urlsplit(v)
        if not v.startswith("/") or v.startswith("//") or "\\" in v or parts.scheme or parts.netloc:
            raise ValueError("path must be a page on this platform, starting with a single /")
        return v


def agent_release(os_name: str, arch: str) -> dict | None:
    """The agent version wall PCs should run, from the manifest written by the build script."""
    manifest = Path(os.environ.get("HSS_WALL_RELEASES", "/srv/wall-agent/manifest.json"))
    try:
        data = json.loads(manifest.read_text())
        f = data["files"][f"{os_name}/{arch}"]
        return {"version": data["version"], "path": f["path"], "sha256": f["sha256"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


@router.post("/nodes/{node_id}/heartbeat", dependencies=[Depends(wall_token)])
def heartbeat(beat: Heartbeat, node_id: str = NODE_ID) -> dict:
    health = beat.model_dump()
    with connect() as conn:
        conn.execute(
            """INSERT INTO wall_nodes (id, hostname, agent_version, os, health)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET hostname = EXCLUDED.hostname,
                   agent_version = EXCLUDED.agent_version, os = EXCLUDED.os,
                   health = EXCLUDED.health, last_seen = now()""",
            (node_id, beat.hostname, beat.agent_version, beat.os, Jsonb(health)),
        )
        rows = conn.execute("SELECT monitor, path FROM wall_layouts WHERE node_id = %s ORDER BY monitor",
                            (node_id,)).fetchall()
    return {"layout": [{"monitor": m, "path": p} for m, p in rows], "agent": agent_release(beat.os, beat.arch)}


@router.get("/nodes", dependencies=[Depends(admin_token)])
def list_nodes() -> list[dict]:
    with connect() as conn:
        nodes = conn.execute("SELECT id, hostname, agent_version, os, first_seen, last_seen, health "
                             "FROM wall_nodes ORDER BY id").fetchall()
        layouts = conn.execute("SELECT node_id, monitor, path FROM wall_layouts ORDER BY node_id, monitor").fetchall()
    now = datetime.now(timezone.utc)
    result = []
    for node_id, host, version, os_name, first, last, health in nodes:
        result.append({
            "id": node_id, "hostname": host, "agent_version": version, "os": os_name,
            "first_seen": first, "last_seen": last,
            "online": (now - last).total_seconds() < ONLINE_SECONDS,
            "cpu_percent": health.get("cpu_percent"), "memory_percent": health.get("memory_percent"),
            "screens": health.get("screens", []),
            "layout": [{"monitor": m, "path": p} for n, m, p in layouts if n == node_id],
        })
    return result


@router.put("/nodes/{node_id}/layout", dependencies=[Depends(admin_token)])
def set_layout(layout: list[MonitorLayout], node_id: str = NODE_ID) -> dict:
    if len({m.monitor for m in layout}) != len(layout):
        raise HTTPException(status_code=422, detail="each monitor may appear once")
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM wall_nodes WHERE id = %s", (node_id,)).fetchone():
            raise HTTPException(status_code=404, detail="unknown wall node; start its agent first")
        conn.execute("DELETE FROM wall_layouts WHERE node_id = %s", (node_id,))
        for m in layout:
            conn.execute("INSERT INTO wall_layouts (node_id, monitor, path) VALUES (%s, %s, %s)",
                         (node_id, m.monitor, m.path))
    return {"node_id": node_id, "layout": [m.model_dump() for m in layout]}
