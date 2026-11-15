# Backups and restore tests

One encrypted file per backup holds: the database, the API data (evidence vault, site plans, branding,
the credentials-vault key, snapshots and clips), the proxy's certificate authority (so phones and wall
PCs keep trusting the server after a restore), and the site config (.env, config/, gateway/cameras.env,
gps/). The console's **Security** page shows the last backup and restore test, and a failed backup is
sent to WhatsApp subscribers of the `system` topic.

## Set up (once)

```bash
cd ~/Smart-Surveillance
sudo mkdir -p /var/backups/hss && sudo chown $USER /var/backups/hss
openssl rand -base64 32 > ~/.hss-backup-pass && chmod 600 ~/.hss-backup-pass
cat ~/.hss-backup-pass
```

**Write the passphrase down and keep it offline** (sealed envelope in the safe, and with the IT
Manager). Without it no backup can be restored. It is never stored inside a backup.

First backup and restore test:

```bash
tools/backup/hss-backup.sh
tools/backup/hss-restore.sh --test
```

Then schedule them (`crontab -e`):

```
30 1 * * * cd ~/Smart-Surveillance && tools/backup/hss-backup.sh >> ~/hss-backup.log 2>&1
15 3 1 * * cd ~/Smart-Surveillance && tools/backup/hss-restore.sh --test >> ~/hss-backup.log 2>&1
```

## A second copy off the server

A backup on the same disk is lost with the disk. Set `HSS_BACKUP_COPY_TO` in `.env` to a NAS share or a
USB drive mounted on the server (for example `/mnt/hss-backup`), and rotate two USB drives weekly so one
is always off site. The files are encrypted (AES-256), so a lost drive doesn't expose the data.

Options in `.env`: `HSS_BACKUP_DIR` (default /var/backups/hss), `HSS_BACKUP_KEEP` (default 14),
`HSS_BACKUP_COPY_TO`. `--no-media` skips snapshots and clips for a smaller file.

## Restore test

`hss-restore.sh --test` checks the file's SHA-256, decrypts it, checks every file inside, restores the
database into a scratch database, checks the main tables and that an administrator exists, reads the
data archive, then drops the scratch database. The live system is untouched.

## Full restore (after a disk failure or on a new server)

1. Install the server as in docs/console.md, clone the repository, copy the backup file and the
   passphrase file onto it.
2. Start the database: `docker compose up -d db`.
3. `tools/backup/hss-restore.sh --full /path/to/hss-YYYYMMDD-HHMM.tar.enc` and type RESTORE.
4. The config files from the backup are saved as `~/hss-YYYYMMDD-HHMM-config.tgz`; restore `.env` and
   the others from it if the new server has none (`tar xzf ... -C ~/Smart-Surveillance`).
5. `docker compose --profile ai --profile notify --profile edge --profile geo up -d`; sign in and check
   Devices, Evidence vault (custody log intact) and Security.

Recordings themselves stay on the NVRs and are not part of this backup.
