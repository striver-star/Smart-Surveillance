#!/usr/bin/env python3
"""Issue HSS per-site licences (vendor side; keep the private key OFF the site servers).

  hss-licence.py keygen --private ~/hss-licensing/vendor.key
      Makes the vendor key pair once. Writes the private key (keep it offline, backed up) and the public key
      to services/api/app/licence_public.key; commit that file so every build checks licences with it.

  hss-licence.py issue --private ~/hss-licensing/vendor.key --licensee "Client Ltd" --site "Main campus" \
      --installation <id from Settings > Licence> --nvrs 7 --cameras 224 --support-until 2027-12-31 \
      --features face_plate,gps --out client-main.hsslicence

  hss-licence.py verify client-main.hsslicence
Needs the 'cryptography' package (pip install cryptography).
"""
import argparse
import base64
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "services" / "api" / "app" / "licence_public.key"
sys.path.insert(0, str(ROOT / "services" / "api"))
FIELDS = ("id", "licensee", "site", "installation_id", "issued", "support_until", "max_nvrs", "max_cameras", "features")
KNOWN = ("face_plate", "gps")


def canonical(lic):
    return json.dumps({k: lic[k] for k in FIELDS}, sort_keys=True, separators=(",", ":")).encode()


def keygen(a):
    p = Path(a.private).expanduser()
    if p.exists():
        sys.exit(f"{p} exists; refusing to overwrite a vendor key")
    p.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    PUBLIC.write_text(base64.b64encode(pub).decode() + "\n")
    print(f"private key: {p} (keep offline and backed up; anyone with it can issue licences)")
    print(f"public key:  {PUBLIC} (commit this file)")


def issue(a):
    key = serialization.load_pem_private_key(Path(a.private).expanduser().read_bytes(), password=None)
    feats = sorted(f for f in a.features.split(",") if f)
    bad = [f for f in feats if f not in KNOWN]
    if bad:
        sys.exit(f"unknown feature(s): {', '.join(bad)}; known: {', '.join(KNOWN)}")
    date.fromisoformat(a.support_until)
    lic = {"id": a.id or f"HSS-{date.today():%Y}-{uuid.uuid4().hex[:8].upper()}", "licensee": a.licensee, "site": a.site,
           "installation_id": a.installation, "issued": str(date.today()), "support_until": a.support_until,
           "max_nvrs": a.nvrs, "max_cameras": a.cameras, "features": feats}
    doc = {"licence": lic, "signature": base64.b64encode(key.sign(canonical(lic))).decode()}
    Path(a.out).write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {a.out}: {lic['id']} for {a.licensee}, {a.site}")


def verify(a):
    from app.licence import verify as check
    try:
        lic = check(Path(a.file).read_text(), PUBLIC.read_text().strip())
    except (ValueError, OSError) as exc:
        sys.exit(f"NOT valid: {exc}")
    print("valid:", json.dumps(lic, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    s = p.add_subparsers(dest="cmd", required=True)
    k = s.add_parser("keygen"); k.add_argument("--private", required=True); k.set_defaults(fn=keygen)
    i = s.add_parser("issue")
    for name in ("private", "licensee", "site", "installation", "support-until"):
        i.add_argument(f"--{name}", required=True)
    i.add_argument("--nvrs", type=int, required=True); i.add_argument("--cameras", type=int, required=True)
    i.add_argument("--features", default=""); i.add_argument("--id", default=""); i.add_argument("--out", required=True)
    i.set_defaults(fn=issue)
    v = s.add_parser("verify"); v.add_argument("file"); v.set_defaults(fn=verify)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
