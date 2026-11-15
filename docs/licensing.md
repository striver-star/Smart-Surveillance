# Per-site licences

Each installation needs a licence file. It is perpetual: the features it covers never expire.
It also records how long updates and support last.

| Without a licence | With a licence |
|---|---|
| Everything works for 30 days after installation | Up to the licence's NVRs and cameras |
| Then: recording, live view, events, alerts and everything already set up keep working; new NVRs and the optional features (face and plate, GPS) can't be turned on | Optional features as listed in the licence |

## Vendor side (once)

On a computer that is **not** a site server:

```bash
pip install cryptography
python3 tools/licence/hss-licence.py keygen --private ~/hss-licensing/vendor.key
git add services/api/app/licence_public.key && git commit -m "Licence public key" && git push
```

Keep `vendor.key` offline and backed up: anyone with it can issue licences, and if it is lost no new
licences can be issued for builds that carry its public key. Builds without `licence_public.key` don't
check licences at all (as during the PoC).

## Issuing a licence

1. The site's administrator opens **Settings › Licence** and sends the **installation id**.
2. Issue:
   ```bash
   python3 tools/licence/hss-licence.py issue --private ~/hss-licensing/vendor.key \
     --licensee "Client Ltd" --site "Main campus" --installation <id> \
     --nvrs 7 --cameras 224 --support-until 2027-12-31 --features face_plate,gps --out client-main.hsslicence
   ```
3. Send the `.hsslicence` file; the administrator loads it under **Settings › Licence**.

Features: `face_plate` (face and number plate recognition), `gps` (guard and vehicle tracking). An
upgrade (more NVRs, a feature) is a new licence file for the same installation id.

A restore onto a new server keeps the installation id (it is in the database), so the licence keeps
working.
