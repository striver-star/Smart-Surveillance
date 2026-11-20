# Reports (Phase 6, built early)

**Status 2026-11-15:** daily, weekly, monthly and custom-period reports in PDF and Word, in the
site's branding, with a plain-language summary, charts, critical incidents with snapshots, busiest
locations, repeat alerts, device health and open items. Archived and searchable in the console,
downloadable, and sent by WhatsApp (email and push as fallback) to the recipients subscribed to
each report type. Optional schedule. 18 API tests pass; tested end to end in the sandbox.

## What each report contains

| Section | Daily | Weekly | Monthly |
| --- | --- | --- | --- |
| Headline figures (events, critical, cameras online, locations) and change against the previous period | yes | yes | yes |
| Plain-language summary (rule-based: every sentence states a figure) | yes | yes | yes |
| Charts | by hour | per day, by hour, busiest locations, comparison | same as weekly |
| Critical incidents with snapshots | up to 12 | up to 10 | up to 8, plus a full incident register |
| Busiest locations and repeat alerts (3+ at the same place) | yes | yes | yes |
| Device health (NVRs, drives, offline cameras, clocks) | yes | yes | yes |
| Open items and recommendations | yes | yes | yes |

Camera names come from the camera survey (`nvr4-ch23` is shown as `SECURITY CHECK 1 (nvr4-ch23)`).
Device health comes from the latest probe files until live monitoring arrives (Phase 3); each
report says when that check was.

## In the console

**Reports** page: choose the type and day (or a custom range, up to 93 days), press **Generate**;
the archive lists every report with PDF and Word downloads; open one to read its summary, send it
now to its subscribers (optionally with the Word file) and see each delivery.
Administrators, the CSO and management can generate and download; administrators and the CSO can send.

## Schedule (off by default)

Add to `.env`, then `docker compose up -d api`:

```
HSS_REPORT_TIME=07:00            # local time (HSS_TZ); empty = off
HSS_REPORT_KINDS=daily,weekly,monthly
HSS_REPORT_FORMATS=pdf           # or pdf,docx
```

Every day at that time the daily report (yesterday) is generated and sent to everyone subscribed
to `daily`; on Mondays also the weekly (last Monday to Sunday) to `weekly`; on the 1st also the
monthly (last month) to `monthly`. Who receives which report is set in WhatsApp & alerts › Recipients. Each report runs
once a day even if the API restarts.

## Files and libraries

Reports are stored under the API's data volume (`/data/reports/YYYY/MM/`). PDF: ReportLab (BSD);
Word: python-docx (MIT); charts: Matplotlib (PSF-style); fonts: DejaVu (bundled with Matplotlib).
ReportLab replaces WeasyPrint from the original plan because it needs no system libraries in the
server image. English only for now; the text is kept in one module so a second language can follow.
