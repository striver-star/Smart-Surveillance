"""Minimal RTSP client for load tests: DESCRIBE, SETUP (RTP over TCP), PLAY, then count bytes.

It never decodes video, so it measures what the NVR delivers, not the server's CPU.
Standard library only. Supports Basic and Digest authentication (Hikvision uses Digest).
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit


class RtspError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass
class Response:
    status: int
    reason: str
    headers: dict[str, str]
    body: bytes = b""


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()  # noqa: S324 - required by RTSP Digest auth


def digest_header(challenge: str, user: str, password: str, method: str, uri: str, nc: int = 1,
                  cnonce: str | None = None) -> str:
    params = dict(re.findall(r'(\w+)="?([^",]*)"?', challenge))
    realm, nonce = params.get("realm", ""), params.get("nonce", "")
    ha1 = _md5(f"{user}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    qop = params.get("qop", "")
    if "auth" in qop.split(","):
        cnonce = cnonce or os.urandom(8).hex()
        ncs = f"{nc:08x}"
        resp = _md5(f"{ha1}:{nonce}:{ncs}:{cnonce}:auth:{ha2}")
        extra = f', qop=auth, nc={ncs}, cnonce="{cnonce}"'
    else:
        resp = _md5(f"{ha1}:{nonce}:{ha2}")
        extra = ""
    opaque = f', opaque="{params["opaque"]}"' if "opaque" in params else ""
    return (f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
            f'response="{resp}"{extra}{opaque}')


class RtspPull:
    """One RTSP session. Call open(), then run(seconds) counts the RTP bytes received."""

    def __init__(self, url: str, user: str = "", password: str = "", timeout: float = 10.0):
        parts = urlsplit(url)
        self.url = url
        self.host, self.port = parts.hostname or "", parts.port or 554
        self.user, self.password, self.timeout = user, password, timeout
        self.sock: socket.socket | None = None
        self.cseq = 0
        self.auth: tuple[str, str] | None = None     # (scheme, challenge)
        self.session = ""
        self.bytes = 0
        self.packets = 0
        self.clock_rate = 90000          # video RTP clock (from the SDP; 90 kHz for H.264/H.265)
        self.media_ticks = 0             # video time received, in RTP clock ticks (wrap-safe)
        self._last_ts: int | None = None
        self.video_packets = 0
        self.lost = 0                    # video RTP packets skipped by the sender (sequence gaps)
        self._last_seq: int | None = None
        self._buf = b""

    # ---------------------------------------------------------------- protocol

    def _auth_header(self, method: str, uri: str) -> dict[str, str]:
        if not self.auth:
            return {}
        scheme, challenge = self.auth
        if scheme == "digest":
            return {"Authorization": digest_header(challenge, self.user, self.password, method, uri)}
        import base64
        return {"Authorization": "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()}

    def _recv_more(self) -> None:
        assert self.sock is not None
        chunk = self.sock.recv(65536)
        if not chunk:
            raise RtspError("connection closed by the NVR")
        self._buf += chunk

    def _read_response(self) -> Response:
        """Read one RTSP response, skipping any interleaved RTP packets in front of it."""
        while True:
            while len(self._buf) < 4:
                self._recv_more()
            if self._buf[0:1] == b"$":
                self._skip_interleaved()
                continue
            while b"\r\n\r\n" not in self._buf:
                self._recv_more()
            head, self._buf = self._buf.split(b"\r\n\r\n", 1)
            lines = head.decode("latin-1").split("\r\n")
            m = re.match(r"RTSP/1\.\d (\d{3}) ?(.*)", lines[0])
            if not m:
                raise RtspError(f"bad response line: {lines[0][:60]}")
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    key = k.strip().lower()
                    headers[key] = (headers[key] + ", " + v.strip()) if key in headers and key == "www-authenticate" else v.strip()
            length = int(headers.get("content-length", "0") or 0)
            while len(self._buf) < length:
                self._recv_more()
            body, self._buf = self._buf[:length], self._buf[length:]
            return Response(int(m.group(1)), m.group(2), headers, body)

    def _skip_interleaved(self) -> int:
        while len(self._buf) < 4:
            self._recv_more()
        size = int.from_bytes(self._buf[2:4], "big")
        while len(self._buf) < 4 + size:
            self._recv_more()
        if self._buf[1] == 0 and size >= 12:          # RTP on the video channel: track its timestamp
            seq = int.from_bytes(self._buf[6:8], "big")
            if self._last_seq is not None:
                gap = (seq - self._last_seq - 1) & 0xFFFF
                if gap < 3000:
                    self.lost += gap
            self._last_seq = seq
            self.video_packets += 1
            ts = int.from_bytes(self._buf[8:12], "big")
            if self._last_ts is not None:
                step = (ts - self._last_ts) & 0xFFFFFFFF
                if step < 0x80000000:                 # ignore the odd backwards timestamp
                    self.media_ticks += step
            self._last_ts = ts
        self._buf = self._buf[4 + size:]
        self.bytes += size
        self.packets += 1
        return size

    def request(self, method: str, uri: str, headers: dict[str, str] | None = None) -> Response:
        for attempt in (1, 2):
            self.cseq += 1
            hdrs = {"CSeq": str(self.cseq), "User-Agent": "hss-nvrload"}
            if self.session:
                hdrs["Session"] = self.session
            hdrs.update(headers or {})
            hdrs.update(self._auth_header(method, uri))
            msg = f"{method} {uri} RTSP/1.0\r\n" + "".join(f"{k}: {v}\r\n" for k, v in hdrs.items()) + "\r\n"
            assert self.sock is not None
            self.sock.sendall(msg.encode())
            resp = self._read_response()
            if resp.status == 401 and attempt == 1 and self.user:
                challenge = resp.headers.get("www-authenticate", "")
                digest = re.search(r"Digest [^\n]*", challenge)
                self.auth = ("digest", digest.group(0)) if digest else ("basic", challenge)
                continue
            return resp
        return resp

    def open(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        r = self.request("DESCRIBE", self.url, {"Accept": "application/sdp"})
        if r.status != 200:
            raise RtspError(f"DESCRIBE refused: {r.status} {r.reason}", r.status)
        base = r.headers.get("content-base") or r.headers.get("content-location") or self.url
        if not base.endswith("/"):
            base += "/"
        sdp = r.body.decode("latin-1")
        video = sdp.split("m=video", 1)
        if len(video) < 2:
            raise RtspError("no video track in the stream description")
        rate = re.search(r"a=rtpmap:\d+ [\w.-]+/(\d+)", video[1])
        if rate:
            self.clock_rate = int(rate.group(1))
        control = re.search(r"a=control:(\S+)", video[1])
        track = control.group(1) if control else ""
        track_url = track if track.startswith("rtsp://") else urljoin(base, track) if track and track != "*" else self.url
        r = self.request("SETUP", track_url, {"Transport": "RTP/AVP/TCP;unicast;interleaved=0-1"})
        if r.status != 200:
            raise RtspError(f"SETUP refused: {r.status} {r.reason}", r.status)
        self.session = r.headers.get("session", "").split(";")[0]
        r = self.request("PLAY", self.url, {"Range": "npt=0.000-"})
        if r.status != 200:
            raise RtspError(f"PLAY refused: {r.status} {r.reason}", r.status)

    def receive_until(self, deadline: float, stop: threading.Event | None = None) -> None:
        """Count bytes until the deadline. Raises RtspError if the stream stops for `timeout` seconds."""
        assert self.sock is not None
        try:
            while time.monotonic() < deadline and not (stop and stop.is_set()):
                if self._buf[0:1] == b"$":
                    self._skip_interleaved()
                elif len(self._buf) >= 4:
                    self._read_response()      # keep-alive answer or server message
                else:
                    self._recv_more()
        except socket.timeout as exc:
            raise RtspError(f"no data for {self.timeout:.0f} s") from exc
        except OSError as exc:
            raise RtspError(f"connection error: {exc}") from exc

    @property
    def media_seconds(self) -> float:
        return self.media_ticks / self.clock_rate

    def close(self) -> None:
        if self.sock is None:
            return
        try:
            self.sock.settimeout(2)
            if self.session:
                self.cseq += 1
                self.sock.sendall(f"TEARDOWN {self.url} RTSP/1.0\r\nCSeq: {self.cseq}\r\nSession: {self.session}\r\n"
                                  .encode() + "".join(f"{k}: {v}\r\n" for k, v in
                                                      self._auth_header("TEARDOWN", self.url).items()).encode()
                                  + b"\r\n")
        except OSError:
            pass
        finally:
            self.sock.close()
            self.sock = None


@dataclass
class PullResult:
    url: str
    label: str
    opened: bool = False
    error: str = ""
    status: int = 0
    bytes: int = 0
    seconds: float = 0.0
    samples: list[int] = field(default_factory=list)   # bytes per second while measuring

    @property
    def kbps(self) -> float:
        return self.bytes * 8 / 1000 / self.seconds if self.seconds else 0.0
