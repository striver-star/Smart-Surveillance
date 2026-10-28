"""Minimal read-only ISAPI client. It only ever sends GET requests."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx


def strip_ns(root: ET.Element) -> ET.Element:
    """Remove XML namespaces so paths like 'deviceInfo/model' work on every firmware."""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
        for key in list(el.attrib):
            if "}" in key:
                el.attrib[key.split("}", 1)[1]] = el.attrib.pop(key)
    return root


@dataclass
class Response:
    path: str
    status: int
    text: str

    @property
    def ok(self) -> bool:
        return self.status == 200

    def xml(self) -> ET.Element | None:
        if not self.ok:
            return None
        try:
            return strip_ns(ET.fromstring(self.text))
        except ET.ParseError:
            return None


class IsapiClient:
    def __init__(self, base_url: str, user: str, password: str, *,
                 verify_tls: bool = True, timeout: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=httpx.DigestAuth(user, password),
            verify=verify_tls,
            timeout=timeout,
            transport=transport,
        )

    def get(self, path: str) -> Response:
        try:
            r = self._http.get(path)
            return Response(path, r.status_code, r.text)
        except httpx.HTTPError as exc:
            return Response(path, 0, f"{exc.__class__.__name__}: {exc}")

    def stream_events(self, seconds: float):
        """Yield raw EventNotificationAlert XML blocks from alertStream for a fixed time."""
        import time
        deadline = time.monotonic() + seconds
        buf = ""
        try:
            with self._http.stream("GET", "/ISAPI/Event/notification/alertStream",
                                   timeout=httpx.Timeout(10.0, read=seconds + 5)) as r:
                if r.status_code != 200:
                    return
                for chunk in r.iter_text():
                    buf += chunk
                    while "</EventNotificationAlert>" in buf:
                        start = buf.find("<EventNotificationAlert")
                        end = buf.find("</EventNotificationAlert>") + len("</EventNotificationAlert>")
                        if start != -1 and start < end:
                            yield buf[start:end]
                        buf = buf[end:]
                    if time.monotonic() > deadline:
                        return
        except httpx.HTTPError:
            return

    def close(self) -> None:
        self._http.close()
