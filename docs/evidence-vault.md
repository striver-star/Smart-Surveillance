# Evidence vault

For alerts that matter later (police, insurance, disciplinary cases), seal the evidence so it can be
shown to be complete and unchanged.

## Sealing

- Open the alert › **Seal evidence**, with a reason and a case reference (optional). Administrators and
  the CSO can seal.
- **Closing an alert as a real incident seals it automatically.**
- A package holds the snapshot, the clip (if one was cut), the event, the alert and its full timeline,
  and `manifest.json` with the SHA-256 of each file. The package's own SHA-256 is recorded in the
  vault, the alert's timeline and the audit log.
- **Export copy** on an alert still gives a one-off copy that is not kept in the vault.

## The Evidence vault page

- Every package with its SHA-256, contents and how long it is kept.
- **Download** first re-checks the package against its SHA-256. If it doesn't match, the download is
  refused and the failure is logged. The file sent carries its SHA-256 in the `X-Evidence-SHA256`
  header; anyone can check a copy with `sha256sum`.
- **Details**: the custody log (sealed, downloaded, verified, legal hold, retention changes, deleted),
  **Verify**, **Legal hold** (with a reason), and, for administrators, the keep-until date.
- The custody log is hash-chained: each entry includes the hash of the one before it. The page checks
  the whole chain each time it opens and shows a red warning if any entry was changed or removed.

## Retention

Packages are kept `HSS_EVIDENCE_DAYS` (default 365) after sealing, then deleted by a clean-up that runs
every 6 hours. Packages on legal hold are never deleted. Deletion is recorded in the custody log.

## Limits

The vault detects changes; it cannot prevent someone with full control of the server from deleting
files. Keep the server's admin accounts few, and back the vault folder (`api-data` volume,
`/data/evidence`) up with the database, ideally to storage that can't be overwritten.
