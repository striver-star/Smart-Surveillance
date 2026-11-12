import json

import httpx
import pytest

from app import notify
from app.notify import Attachment, EmailSender, PushSender, Recipient, WhatsAppSender, dispatch

CSO = Recipient("CSO", "cso", whatsapp="+2348011112222", email="cso@example.com", subscriptions=["critical", "daily", "test"])
MGMT = Recipient("Management", "management", email="md@example.com", subscriptions=["weekly", "monthly"])
IT = Recipient("IT Manager", "it", whatsapp="+2348033334444", subscriptions=["daily", "device", "system"])
PDF = Attachment("daily.pdf", "application/pdf", notify.test_pdf(["hello"]))


def gateway(ready=True, fail_for=()):
    sent = []

    def handler(req: httpx.Request):
        if req.url.path == "/send":
            body = json.loads(req.content)
            if not ready:
                return httpx.Response(503, json={"error": "WhatsApp is not connected", "status": "qr"})
            if body["to"] in fail_for:
                return httpx.Response(422, json={"error": f"{body['to']} is not on WhatsApp"})
            sent.append(body)
            return httpx.Response(200, json={"id": f"msg{len(sent)}"})
        return httpx.Response(404)
    return WhatsAppSender("http://wa", "t", transport=httpx.MockTransport(handler)), sent


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    return EmailSender({"HSS_SMTP_HOST": "mail", "HSS_SMTP_FROM": "hss@example.com"})


def no_push():
    return PushSender("", "")


def test_whatsapp_first_with_document(smtp):
    wa, sent = gateway()
    attempts = dispatch("daily", "Daily report", "38 events", PDF, [CSO, MGMT, IT], wa, smtp, no_push())
    assert [(a.recipient, a.channel, a.status) for a in attempts] == [("CSO", "whatsapp", "sent"), ("IT Manager", "whatsapp", "sent")]
    assert sent[0]["document"]["filename"] == "daily.pdf" and FakeSMTP.sent == []
    assert attempts[0].address == "…2222", "phone numbers are masked in the log"


def test_email_fallback_when_gateway_not_linked(smtp):
    wa, _ = gateway(ready=False)
    attempts = dispatch("daily", "Daily report", "38 events", PDF, [CSO, IT], wa, smtp, no_push())
    channels = [(a.recipient, a.channel, a.status, a.is_fallback) for a in attempts]
    assert ("CSO", "whatsapp", "failed", False) in channels and ("CSO", "email", "sent", True) in channels
    assert ("IT Manager", "whatsapp", "failed", False) in channels  # no e-mail address: nothing else to try
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "cso@example.com" and any(p.get_filename() == "daily.pdf" for p in msg.iter_attachments())


def test_only_subscribed_recipients_and_push_for_alerts(smtp):
    wa, sent = gateway()
    pushed = []
    push = PushSender("http://ntfy", "hss-alerts", transport=httpx.MockTransport(
        lambda r: (pushed.append(r.headers["Title"]), httpx.Response(200))[1]))
    attempts = dispatch("critical", "Intrusion at fence", "Zone 3", None, [CSO, MGMT, IT], wa, smtp, push)
    assert [a.recipient for a in attempts if a.channel == "whatsapp"] == ["CSO"]
    assert pushed == ["Intrusion at fence"]


def test_unknown_number_falls_back_to_email(smtp):
    wa, _ = gateway(fail_for={"+2348011112222"})
    attempts = dispatch("test", "Test", "hi", None, [CSO], wa, smtp, no_push())
    assert attempts[0].detail.endswith("is not on WhatsApp") and attempts[1].channel == "email"


def test_test_pdf_is_a_pdf():
    pdf = notify.test_pdf(["HSS delivery test", "(brackets) ok"])
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF") and b"startxref" in pdf


def test_load_recipients_ignores_unknown_fields(tmp_path):
    f = tmp_path / "r.json"
    f.write_text(json.dumps([{"name": "CSO", "whatsapp": "+234", "subscriptions": ["test"], "note": "x"}]))
    assert notify.load_recipients(f)[0].name == "CSO"
    assert notify.load_recipients(tmp_path / "missing.json") == []


def test_shared_number_gets_one_copy_and_no_email_is_fine():
    wa, sent = gateway()
    gm = Recipient("GM", "management", whatsapp="+234 803 111 2222", subscriptions=["test"])
    cso = Recipient("CSO", "cso", whatsapp="+2348031112222", subscriptions=["test"])
    attempts = dispatch("test", "Test", "hi", None, [gm, cso], wa, EmailSender({}), no_push())
    assert len(sent) == 1
    assert [(a.recipient, a.status) for a in attempts] == [("GM", "sent"), ("CSO", "skipped")]
