"""Credentials vault: device passwords are stored encrypted, never in plain text.

Encryption is Fernet (AES-128-CBC with HMAC-SHA256, from the `cryptography` package). The key comes from
HSS_VAULT_KEY in .env, or, if that's empty, from a key file the API creates on first use
(/data/vault.key, readable only by the API). Back the key up with the database backup: without it the
stored NVR passwords can't be read, and every NVR has to be re-entered.

Rotating the key: put the new key first and the old one after it, comma separated
(HSS_VAULT_KEY=new,old), restart the API, then run `python -m app.vault rotate`. Afterwards the old key
can be removed.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class VaultError(RuntimeError):
    pass


def _key_file() -> Path:
    return Path(os.environ.get("HSS_DATA_DIR", "/data")) / "vault.key"


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    keys = [k.strip() for k in os.environ.get("HSS_VAULT_KEY", "").split(",") if k.strip()]
    if not keys:
        f = _key_file()
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(Fernet.generate_key())
        keys = [f.read_text().strip()]
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except ValueError as exc:
        raise VaultError("HSS_VAULT_KEY is not a valid key; make one with: "
                         "python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'") from exc


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise VaultError("stored password can't be decrypted: the vault key changed or is missing") from exc


def rotate_all() -> int:
    """Re-encrypt every stored secret with the first (newest) key."""
    from .db import connect
    n = 0
    with connect() as conn:
        for nid, secret in conn.execute("SELECT id, secret FROM nvrs").fetchall():
            conn.execute("UPDATE nvrs SET secret = %s WHERE id = %s", (_fernet().rotate(secret.encode()).decode(), nid))
            n += 1
    return n


if __name__ == "__main__":
    if sys.argv[1:] == ["rotate"]:
        print(f"re-encrypted {rotate_all()} stored password(s) with the first key in HSS_VAULT_KEY")
    elif sys.argv[1:] == ["new-key"]:
        print(Fernet.generate_key().decode())
    else:
        sys.exit("usage: python -m app.vault new-key | rotate")
