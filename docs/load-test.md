# Load test (Phase 8 gate: 20 NVRs)

`tools/loadtest/hss-loadtest.py` simulates NVRs posting events (20% with a snapshot) and health checks to
the API and measures response times. It never sends critical events, so no WhatsApp messages go out.

```bash
cd ~/Smart-Surveillance
docker compose run --rm --no-deps -v ./tools/loadtest:/lt api python /lt/hss-loadtest.py --nvrs 20 --cameras 32 --events-per-cam-min 2 --minutes 10
docker compose run --rm --no-deps -v ./tools/loadtest:/lt api python /lt/hss-loadtest.py --cleanup
```

Pass: p95 under 500 ms, errors under 0.1%, and at least 95% of the asked rate delivered.

## Results in the build environment (4 CPU cores, 15 GB, 2026-11-15)

| Load | Rate asked | Rate handled | p95 | p99 | Errors | Verdict |
|---|---|---|---|---|---|---|
| 20 NVRs x 32 cameras, 2 events per camera per minute | 21.3/s | 21.3/s | 37 ms | 42 ms | 0 | PASS |
| Same, 10 events per camera per minute (5x) | 106.7/s | 95.9/s | 1,039 ms | 1,312 ms | 0 | saturated |

The API handles about 95 events per second on 4 cores, about 4.5 times a busy 20-NVR site. Run the test
on the site server too (it has its own CPU) and keep the result with the Phase 8 gate. If a site needs
more, the next step is running the event intake in several processes.
