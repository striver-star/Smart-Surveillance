# Hikvision Security Surveillance System: AI Collaboration Context Document

*Version 0.5 \| Owner: IT Manager (Builder) \| Status: Phase 0 build
started; builder answers recorded, 28 October 2026 \| Paste this
document at the start of any new AI session.*

## 1. How to Use This Document

This is a living context file. At the start of every AI session, paste
it in full and state the task (for example: "Using this context,
generate the backend schema for the alerts module"). After each session,
update Section 14 (Decision Log) and Section 15 (Progress Tracker) so
the next session starts with current facts.

**What is new in v0.5:** the builder approved every AI proposal in the
Decision Log, chose the free self-hosted WhatsApp gateway (Provider A),
and answered the open questions: the NVR model is DS-7632NXI-K2/16P,
three Core i5 wall PCs drive 55 inch Hisense TVs, face and plate
recognition should cover most cameras, 10 Android phones start GPS
tracking, licensing is per site and perpetual, deployment is both
on-premises and hosted, branding is selectable and uploadable, and a
Windows server installer is wanted as a backup. Three of these answers
raise conflicts that need a builder decision; they are marked
**Conflict** in Sections 12 and 14. Building has started: Steps 0 and 1
of the PoC are complete (Section 15), and Section 23 holds the master
task list. Section 21 lists every change.

**Instruction to the AI:** Treat this document as the source of truth.
If a request conflicts with it, point out the conflict before
proceeding. If information is missing, list your assumptions explicitly,
then continue. Do not silently invent requirements.

## 2. Roles and Working Agreement

| Role                             | Responsibility                                                                                                                                                                                            |
|----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Builder / IT Manager (human)** | Oversees design and the full development lifecycle through implementation and deployment. Reviews outputs at each stage, validates against client requirements, decides scope, and explores new features. |
| **AI collaborator**              | Generates code, handles frontend and backend development, UX and UI design, product bundling and packaging, documentation, tests, and deployment scripts.                                                 |
| **IT Team (operators)**          | Day-to-day operation, monitoring, and maintenance of the system after deployment.                                                                                                                         |
| **Client**                       | Source of requirements and final acceptance.                                                                                                                                                              |

**Working rules for the AI:**

1.  Deliver complete, runnable code with file paths, not fragments,
    unless asked otherwise.

2.  Work in small, reviewable stages. End each stage with a short
    checklist the builder can use to verify it.

3.  Explain decisions briefly, in plain language. The builder is a
    manager, not necessarily the day-to-day coder.

4.  Flag risks (security, privacy, performance, licensing, camera or NVR
    firmware limits) as soon as you see them.

5.  Use only free and open-source software, apart from the declared
    exceptions in Section 19. Avoid vendor lock-in beyond the existing
    Hikvision devices. If something appears to need a paid or
    proprietary tool, flag it and propose a free open-source
    alternative.

6.  Never hard-code credentials. Use environment variables or a secrets
    manager.

7.  Ask at most one or two clarifying questions at a time, and only when
    the answer changes the design.

## 3. Product Overview

**Product name:** Security Surveillance System based on Hikvision
products (working title; final brand name to be decided).

**One-line description:** A centralized, AI-driven security monitoring
platform that unifies Hikvision NVRs and cameras into one control room
experience, with live wall displays, smart alerts, geo-aware features,
and automated reporting delivered over WhatsApp.

**Problems it solves:**

- Geofencing (virtual boundaries and zone breaches)

- Geotagging (location context for every camera, event and asset)

- Theft detection and response

- Security breach detection (intrusion, tampering, after-hours access)

- Low-light and night-time visibility (night vision and low-light AI)

**Core principle (revised in v0.4):** Edge first, server assisted, and
free and open source throughout. Use the AI built into Hikvision cameras
and NVRs wherever it exists. For non-AI ("dumb") cameras and for face
and plate recognition, the platform runs its own open-source AI workers
on NVIDIA GPUs (or Intel hardware). Every piece of software we write or
ship must be free and open source. The declared exceptions (Section 19)
are the existing Hikvision devices, WhatsApp itself, NVIDIA drivers and
CUDA (free to use, closed source), Windows on the wall PCs, Windows on a
server only as a backup install option, and hosting infrastructure for
the hosted option.

## 4. Users and Stakeholders

| User                  | Needs                                                              |
|-----------------------|--------------------------------------------------------------------|
| Control room operator | Live wall, rotating views, fast alert triage, one-click video jump |
| Security supervisor   | Incident review, evidence export, shift handover, reports          |
| IT Team               | Device health, user management, backups, updates, audit logs       |
| IT Manager            | Oversight dashboards, SLAs, reporting, configuration approval      |
| Client management     | Daily, weekly and monthly summaries by WhatsApp and PDF            |

## 5. Functional Requirements

### 5.1 Live Monitoring Displays

1.  **NVR full-grid screens:** Each NVR gets its own dedicated screen
    showing all of its **32 channels** in a grid view. One screen per
    NVR (example: 3 NVRs means 3 screens).

2.  **Rotating spotlight screen:** A separate screen shows **4 cameras
    at a time for 5 seconds**, then automatically advances to the next
    set of 4, looping continuously across all cameras.

    - Rotation interval (5 s) and group size (4) must be configurable.

    - Pause on hover or click, and jump to a specific camera.

    - If an alert fires, the related camera can be pinned or promoted
      into the rotation (configurable).

3.  **Multi-monitor support:** Each screen can be opened as its own
    browser window or kiosk-mode display, assignable to a monitor or
    video wall.

- **Wall node model:** Scale is 6 NVRs now and up to 20, which means 7
  screens at the start (6 grids plus the rotation screen) and up to 21
  later. One PC cannot decode that many streams. Use dedicated wall PCs
  (Windows or Linux), each running the Wall Agent and a kiosk browser
  that loads a saved layout from the platform. Plan one wall PC per 2
  monitors until the PoC bake-off measures the real limit.

- **Site wall hardware (v0.5):** three wall PCs already exist (Intel
  Core i5, 16 GB RAM) with room for more, and the displays are 55 inch
  Hisense smart TVs. Six NVRs need seven screens, so either one PC
  drives three TVs or a fourth PC is added; the PoC bake-off (Section
  20) decides. The TVs are used only as displays: the platform does not
  run in the TV's own browser. Set each TV to PC or Game mode, turn off
  overscan, eco standby and auto input switching, and fix the HDMI
  input.

- **Pull each stream once:** The stream gateway connects to each camera
  or NVR stream once and fans it out to every viewer. Wall PCs never
  pull directly from the NVR, because NVRs limit concurrent connections
  and outgoing bandwidth.

- **Pre-connect the next group:** The rotation screen opens the next 4
  streams before the switch, so there is no black frame at the 5 second
  change.

4.  **Stream management:** Use sub-streams for grid views (low
    bandwidth) and main streams for spotlight or full-screen views.
    Auto-reconnect when a stream drops.

### 5.2 AI and Analytics (Use Device Capabilities in Full)

The platform must discover which analytics each NVR and camera supports
and enable them through the device APIs where possible. Candidate
capabilities (verify per model and firmware):

- Perimeter protection: line crossing and intrusion (region) detection,
  region entrance and exit

- Smart motion detection with human and vehicle classification (reduces
  false alarms)

- Loitering, unattended baggage, and object removal detection
  (theft-relevant)

- Face detection and face capture, and optional face recognition with
  watchlists (subject to legal and privacy review)

- ANPR / license plate recognition with allow and block lists (if the
  camera supports it)

- People counting and heat map

- Video tampering, scene change, defocus and video loss detection

- Audio exception detection (if audio hardware is present)

- Low-light and DarkFighter or ColorVu enhanced night imaging, and IR
  scheduling

- Fire and smoke detection, and PPE detection where supported

- Alarm input and output (sirens, strobe lights, relays), two-way audio

**Rule:** All events must be normalized into one internal event schema
(see Section 8) regardless of the source device or event type.

### 5.3 Geofencing

Confirmed in v0.2: both meanings are in scope. The platform owns all
geofence definitions as the single source of truth (see 5.11 for the GPS
design).

- **Virtual zone geofencing (camera-based):** Draw zones on the camera
  view or site map. Breach (intrusion, line crossing) triggers an alert.
  Schedules per zone (for example, armed 18:00 to 06:00).

- **GPS geofencing (map-based):** If vehicles, guards or mobile assets
  carry GPS devices or the guard app, define polygon or radius
  boundaries on a map and alert on entry or exit.

### 5.4 Geotagging

- Every NVR, camera, and zone has coordinates (latitude and longitude)
  plus site, building, floor, and bearing or field-of-view direction.

- Every event, snapshot, and clip inherits the geotag of its source.

- Interactive site map and floor plan view showing cameras, with live
  status colors and alert pulses.

- Reports include location context (site, zone, camera name,
  coordinates).

### 5.5 Alerts and Incident Management

- Real-time alert feed with snapshot, short clip, camera, zone, time,
  type, and confidence.

- Severity levels (info, warning, critical) with configurable rules (for
  example: human intrusion in a restricted zone after hours = critical).

- Notification channels: on-screen, sound, WhatsApp (see 5.7), email
  through any SMTP server, and push through self-hosted ntfy. SMS is
  dropped because it depends on paid carrier gateways.

- Acknowledge, assign, comment, and close workflow with a full audit
  trail.

- Incident record bundling video evidence, snapshots, notes, and
  timeline. Evidence export with checksum.

- Escalation: unacknowledged critical alerts escalate to the next
  contact after a set time.

### 5.6 Reporting

Automated **daily, weekly, and monthly** reports in **both Word (.docx)
and PDF** formats.

| Report  | Typical contents                                                                                                               |
|---------|--------------------------------------------------------------------------------------------------------------------------------|
| Daily   | Event totals by type, critical incidents with snapshots, camera and NVR health and downtime, notable zone breaches, open items |
| Weekly  | Trends versus prior week, top locations and times of incidents, repeat alerts, device uptime, action items                     |
| Monthly | Executive summary, charts, month-over-month comparison, incident register, device health and storage trends, recommendations   |

- Report content includes both narrative text (plain-language summary)
  and charts and tables.

- Generation on a schedule (configurable time and timezone), plus
  on-demand generation for any date range, site, or camera.

- Templates are branded and editable. Each tenant uploads its own logo
  and chooses its colors, report language and timezone in the settings
  screen; users can choose their own UI language and timezone.

- Reports are archived and searchable in the platform.

### 5.7 WhatsApp Delivery

- Send reports (PDF and optionally DOCX) and critical alerts to
  configured recipients or groups.

- **Pluggable delivery providers (v0.3):** WhatsApp itself is
  proprietary, and Meta's official API is a paid per-message service, so
  no fully free official route exists. The platform therefore sends
  through a provider interface with these adapters:

<!-- -->

- **Provider A, self-hosted open-source gateway (chosen default):** whatsapp-web.js (Apache 2.0) or Baileys (MIT), linked to the
  client's dedicated number. It is free but unofficial, so it can breach
  WhatsApp terms and the number may be restricted. Mitigation: dedicated
  number, low volume (a few documents a day to 3 recipients), no
  marketing messages, recipients who have saved the number, session
  health checks, and automatic email fallback.

- **Provider B, official WhatsApp Business Cloud API (optional
  exception):** compliant and reliable, but it is a Meta service with
  per-message charges for templates, not a software license. Enable it
  only if the builder approves the exception.

- **Always-on free fallback:** email through a self-hosted or existing
  SMTP server, and push alerts through self-hosted ntfy (Apache 2.0).

<!-- -->

- Delivery tracking (sent, delivered, read, failed) with retry and
  fallback to email.

- Recipient management by role, site, and report type, with opt-in
  records.

<!-- -->

- **Confirmed recipients:** Management, the CSO and the IT Manager.
  Proposed subscriptions: Management receives the weekly and monthly
  executive PDF. The CSO receives the daily report plus critical alerts.
  The IT Manager receives the daily report, device health alerts and
  system alerts. Subscriptions remain editable per recipient.

- **Setup notes:** Use a dedicated phone number for the platform. For
  Provider A, link the number once by QR code, keep volume low, and let
  the platform fall back to email automatically if the gateway session
  drops. Send reports as PDF, with DOCX optional.

<!-- -->

- **Decision (v0.5):** Provider A, the free self-hosted gateway, is the
  default, with automatic email fallback. Provider B stays available as
  an optional, paid exception and is not enabled.

### 5.8 Features You May Have Missed (Recommended) – Integrate these into the system

**Status in v0.2:** all items below are in scope, as instructed by the
builder. Sequencing is in Section 20 so that the first client release is
not delayed by every feature at once.

**Operations and monitoring**

- Device health monitoring: online and offline status, HDD health,
  storage remaining, recording gaps, temperature, firmware version, time
  sync (NTP) drift

- Camera and NVR downtime alerts, and a "cameras not recording" daily
  check

- Event timeline and fast video playback search by time, camera, event
  type

- Smart search (find people, vehicles, or objects by attributes where
  the device supports it)

- Shift handover notes and operator logbook

- Snapshot-on-event and short clip auto-capture around alerts (pre and
  post roll)

- PTZ control, presets, and patrol tours

- Arm and disarm schedules, and a master panic or lockdown mode

**Security and access**

- Role-based access control (admin, supervisor, operator, viewer, client
  read-only) with per-site and per-camera permissions

- Two-factor authentication, strong password policy, session timeout

- Full audit log of who viewed, exported, changed settings, and deleted

- Privacy masking and restricted camera lists

- Encrypted device credentials, TLS everywhere, and network segmentation
  guidance (cameras on an isolated VLAN)

**Resilience**

- Offline-tolerant ingestion: events queued if the link to a device
  drops, and back-filled when it returns

- Backup and restore of configuration, plus database backups

- High availability and graceful degradation (the wall keeps working if
  the reporting service is down)

- Failover storage guidance and retention policy management (for
  example, 30 days continuous, 90 days events)

**Integrations and growth**

- Access control and intercom integration (Hikvision access control
  devices) and door event correlation

- Alarm panel and relay integration, siren and light triggers

- Open REST API and webhooks for third-party integration

- Multi-site and multi-tenant support (clients and branches), with
  per-tenant branding

- Mobile-friendly PWA or companion app for supervisors and guards,
  including guard patrol check-ins with GPS

- Dark mode and large-screen control room mode

- Multilingual UI (English first; add others as needed)

**Analytics and intelligence**

- Anomaly detection (for example, unusual after-hours activity at a
  camera that is normally quiet)

- Incident heat maps by time and place

- False alarm tuning dashboard (which rules cause the most noise)

- Cross-camera event correlation (same person or vehicle across cameras
  where supported)

- Compliance, data retention, and privacy reporting

**Commercial and delivery**

- Installer and onboarding wizard: scan network, discover Hikvision
  devices, add with credentials, auto-import channel lists

- Licensing and activation of our own product (in-house license service,
  if sold to multiple clients)

- Product bundling: Linux server installer script, VM image, Docker
  Compose or Podman package, Windows installer (.exe) for wall PCs,
  documentation, quick start guide, admin manual, and operator training
  material

### 5.9 Analytics Tier Model and Server-Side AI (new in v0.2)

The site mixes ColorVu, AcuSense and non-AI cameras. ColorVu is an
imaging feature (full-time color at night), not an analytics feature, so
it does not by itself produce smart events. On discovery the platform
assigns each channel an analytics tier, which an administrator can
override.

| **Tier**         | **Camera type**                                                 | **Where analytics run**                                                   | **What we use**                                                                                                                                                                        |
|------------------|-----------------------------------------------------------------|---------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| E (Edge)         | AcuSense and other AI cameras                                   | On the camera                                                             | Human and vehicle classification, line crossing, intrusion, tamper, received as ISAPI events. Lowest cost and preferred.                                                               |
| N (NVR-assisted) | Non-AI cameras on NVRs that offer analytics                     | On the NVR                                                                | Some AcuSense class NVRs can analyze a limited number of non-AI channels. Verify per NVR model before relying on it.                                                                   |
| S (Server)       | Non-AI cameras, plus face and plate where hardware cannot do it | Our open-source AI workers on NVIDIA GPUs (Intel OpenVINO as alternative) | Open-source detector (ONNX Runtime with TensorRT) on the sub-stream at about 5 frames per second, with zone and schedule rules, producing the same normalized events as Tiers E and N. |

- Every channel also gets basic health and image-quality checks
  regardless of tier: video loss, frozen frame, lens blocked or dirty,
  and too dark at night. This covers the night vision requirement for
  cameras that have no AI.

- For ColorVu and IR cameras, the platform reads and can schedule the
  supplement light mode through ISAPI where the model supports it.

- Analytics coverage dashboard: percent of channels per tier, so the IT
  Manager can see where server AI capacity is carrying the load and
  which cameras are worth replacing with AI models.

- Cost rule: when many channels need Tier S, compare the cost of another
  GPU with swapping the most critical non-AI cameras (gates, cash
  points, perimeter) for AcuSense models.

- Evaluate in the PoC: our own worker using ONNX Runtime (TensorRT on
  NVIDIA, OpenVINO on Intel) versus the open-source Frigate project (MIT
  license) as an analytics engine. Both must pass the policy in Section
  19.

### 5.10 Face and Plate Recognition (new in v0.2)

Required by the client. Treat it as a separate, controlled module with
its own approval gate.

- **Watchlist based:** Match against enrolled lists (staff, visitors,
  blocked persons, allowed and blocked plates). Do not run open-ended
  identification of everyone. Unmatched faces are discarded or kept only
  for the retention period set in policy.

- **Coverage (v0.5):** The builder wants recognition on most cameras,
  not only entrances. Recognition still needs a frontal face with
  roughly 60 to 90 pixels between the eyes (a commonly cited guideline),
  and plates need a narrow angle, fast shutter and IR light, so a
  general-coverage camera will often see a face too small or too angled
  to match. The platform therefore enables recognition on any camera
  that passes a per-camera qualification test (face size, angle and
  light measured on real footage) and records the result in the
  compatibility matrix. Cameras that fail are offered for repositioning
  or replacement. **Conflict to note:** broad recognition multiplies GPU
  load (Section 17) and makes the legal case harder, because the data
  protection impact assessment must justify identifying people across
  the whole site, not only at controlled entry points.

- **Edge first:** Prefer Hikvision face-capture and ANPR cameras at
  those points and read their ISAPI events. Use the open-source server
  engine as a supplement or for cameras without the feature.

- **Server engine:** Face detection and recognition and plate detection
  and OCR run in the AI workers using only free open-source models and
  weights (YuNet and SFace for faces, YOLOX or RT-DETR with PaddleOCR
  for plates; see Section 19). Plate models must be tested and
  fine-tuned on local plate formats. Training data must also be open:
  many face datasets are non-commercial, so use only datasets with
  permissive terms or the client's own footage with consent.

- **Measure, do not assume:** Test on real footage from the client site
  and record true match rate, false match rate and plate read accuracy
  in day and night conditions before go-live.

- **Human in the loop:** A match is a lead, not proof. Show confidence,
  require operator confirmation before escalation, and log every match
  review.

- **Legal gate:** Biometric data used to identify a person is sensitive
  personal data under the Nigeria Data Protection Act 2023. Before
  go-live: counsel review, a data protection impact assessment, lawful
  basis, signage, access limits, retention limits, and written client
  sign-off. Start this early because it can take longer than the code.

### 5.11 GPS Geofencing and Guard Tracking (new in v0.2)

- **Use Traccar (Apache 2.0)** as the GPS ingestion service. It already
  supports a very large range of hardware vehicle trackers and has
  client apps for phones. Do not build tracker protocols from scratch.

- **Platform owns the geofences:** Polygons and schedules live in our
  database. Positions from Traccar are evaluated with PostGIS, so camera
  zones and GPS zones share one editor, one rule engine and one alert
  flow.

- **Camera zones:** Where the camera supports it, zone definitions are
  pushed to the device through ISAPI so detection happens at the edge.
  Otherwise they are applied by Tier S workers.

- **Devices (v0.5):** Start with 10 Android guard phones running the
  open-source Traccar Client app, which reports over the open OsmAnd
  protocol. Vehicle trackers are not bought yet: choose models whose
  protocol is documented and supported by Traccar, so no vendor cloud
  is needed.

- **Guards:** A browser app can only track location reliably while it is
  open in the foreground (especially on iPhone). For continuous tracking
  use the Traccar client app or a small native Android app, and keep the
  web app for check-ins and incident notes.

- Typical events: vehicle or guard enters or leaves a zone, missed
  patrol checkpoint, vehicle moving after hours, device offline.

### 5.12 Multi-Tenancy and Licensing (new in v0.2)

- **Deployment model (confirmed in v0.5):** Both on-premises and hosted.
  Every install is tenant-ready from day one (tenant_id on every table
  and PostgreSQL row-level security). On-premises comes first. In the
  hosted option the platform runs on a server the builder rents, while
  the NVRs and video stay on the client's site: a small site connector
  on the client network links to the hosted platform over WireGuard and
  sends events, snapshots and health, and pulls live video only when
  someone watches. Hosting is infrastructure the client pays for, like
  hardware, so it is a declared exception (Section 19). Hosted data must
  stay within the rules of the Nigeria Data Protection Act 2023, so
  choose the hosting region with that in mind.

- **License file:** A signed license (for example Ed25519 signatures
  using libsodium or the Python cryptography library) carrying tenant,
  expiry, channel or NVR limit and feature flags such as face and plate,
  GPS, multi-site. Verified offline so the system keeps working without
  internet.

- **Activation:** Optional online activation against a small license
  service that you operate, with a hardware fingerprint and a grace
  period. Be realistic: licensing deters casual copying, and the
  contract does the rest.

- **Metering (decided in v0.5):** Licensed per site, perpetual. Feature
  flags (face and plate, GPS, hosted) and an NVR or channel ceiling sit
  inside each site license. The builder operates the license service.

- **Platform decision (v0.4):** The platform server, database and AI
  workers run on Linux (Debian or Ubuntu Server LTS, free and open
  source) with Docker Engine or Podman. This is the primary, supported
  server platform. The wall PCs may run Windows or Linux, and a Windows
  installer (.exe) is provided for them.

- **Windows server installer as a backup (v0.5):** For a client whose
  server can only run Windows, a Windows installer (.exe, built with
  NSIS) installs the same platform inside WSL2: it enables WSL2, imports
  a Debian image, installs Docker Engine there (not Docker Desktop),
  and starts the same Compose stack. NVIDIA GPUs work through the CUDA
  on WSL driver. It is a backup path with lower performance and more
  moving parts, so it is tested at each release but not recommended for
  sites above 6 NVRs. Windows must already be licensed with the server;
  no Windows Server license is bought for the product.

- **Wall Agent and Windows installer (revised in task 22):** The
  installer sets up a small Wall Agent (one Go program, no runtime
  needed). A Windows service cannot show windows on screen (Session 0
  isolation), so the agent runs in the auto-signed-in wall user's
  session, started at sign-in by a scheduled task that also restarts it
  within a minute if it stops. The agent opens a kiosk browser on each
  monitor, shows the page the platform assigns to that monitor, restarts
  a browser that crashes or whose page stops reporting, keeps a cached
  layout for platform outages, reports health and CPU load to the
  platform, and updates itself with a checksum check. It supports silent
  installation so the IT Team can deploy it to several PCs.

- **Open-source tooling for the installer:** Build with NSIS (zlib
  license); the agent is written in Go (BSD license); Windows Task
  Scheduler (part of Windows) starts it. Chromium in kiosk mode on
  multi-TV PCs (Firefox cannot be placed on a chosen monitor). Google
  Chrome and Microsoft Edge are not used. Wall PCs do not need Docker.

- **Windows hardening for walls:** Use Windows 11 Pro or Enterprise with
  automatic sign-in, a scheduled maintenance window for updates so the
  wall is not restarted during operations, and optional Assigned Access
  kiosk settings. A Linux wall PC image remains available as a fallback.

- **Code signing (optional):** Unsigned installers show a SmartScreen
  warning. Because the IT Team deploys to managed PCs, allow-listing the
  installer is acceptable. A paid code-signing certificate would be an
  extra declared exception, so it is not assumed.

### 5.13 Evidence, Backup and Retention (new in v0.2)

- **Video retention:** 30 days on the NVRs, sized in Section 18.

- **Evidence vault:** When an alert becomes an incident, the platform
  downloads the relevant clip from the NVR through ISAPI into its own
  evidence store, so the footage survives past the 30 day overwrite.
  Evidence retention is set per tenant (for example 12 months) and
  exports carry a checksum.

- **External drive backup (clarified):** The external drive or NAS holds
  the evidence vault, the database and the configuration, backed up
  nightly and encrypted. It does not hold a copy of all 30 days of
  video, which would need as much storage as the NVRs. Manual NVR clip
  export to USB remains available for special cases.

- **3-2-1 rule:** Three copies, two media, one off-site. With reliable
  internet, an encrypted off-site copy is practical. Test a restore
  every quarter.

- **Retention audit:** A daily check confirms each channel really holds
  the expected number of days and flags recording gaps.

## 6. Non-Functional Requirements

- **Performance:** Grid of 32 channels per NVR rendered smoothly using
  sub-streams. Target alert-to-screen latency under 3 seconds.

- **Scalability:** First release targets 6 NVRs (192 channels). Design
  target is 20 NVRs (640 channels), multiple subnets and multiple
  tenants without re-architecture.

- **Reliability:** 99.5% or higher platform availability target.
  Auto-reconnect and self-healing for streams.

- **Security:** Least privilege, encrypted storage of secrets, secure by
  default, regular dependency updates.

- **Usability:** Operators should be productive after a short training.
  Keyboard shortcuts and minimal clicks to reach video.

- **Maintainability:** Clean modular code, automated tests, documented
  APIs, and infrastructure as code.

- **Compliance:** Respect local data protection law (for example Nigeria
  Data Protection Act) for video, face, and plate data. Signage and
  retention policies are part of the deliverable.

<!-- -->

- **License hygiene:** Ship and run only free and open-source
  components, preferring permissive licenses (see Section 19).

- **Bandwidth budget:** Allow about 1 Mbps per sub-stream into the
  stream gateway (roughly 192, 320 and 640 Mbps at 6, 10 and 20 NVRs)
  plus main streams for the rotation screen and for AI workers. Measure
  it in the PoC.

## 7. Proposed Architecture (Starting Point, Open to Revision)

**Device integration layer**

- **ISAPI (HTTP/XML/JSON)** for device configuration, capabilities
  discovery, status, and event subscription (alertStream).

- **RTSP** for live and playback streaming. **ONVIF** (Profiles S, T
  and G) is added as a secondary path for interoperability and for older
  firmware. **ISUP (EHome)** is out of scope: it depends on Hikvision's
  proprietary SDK and is only needed for devices behind NAT. Other
  subnets are reached by routing, VPN or a lightweight collector agent.

- **Decision (v0.2):** HikCentral and Hik-Connect are not used. The
  platform talks directly to devices through a device adapter layer:
  ISAPI first, ONVIF as fallback, RTSP only for basic cameras. A
  compatibility matrix records what each model and firmware supports.

- **PoE cameras behind the NVR (v0.5):** The DS-7632NXI-K2/16P powers
  cameras through its own PoE ports, which puts them on the NVR's
  internal network (usually 192.168.254.x) where the platform cannot
  reach them directly. The platform takes their video through the NVR's
  RTSP channels and their events through the NVR's alertStream. Pushing
  zone settings to a camera needs the NVR's ISAPI pass-through or
  Virtual Host feature, which the PoC tests.

**Platform services**

- **Device Service:** discovery, credentials vault, health polling

- **Event Service:** ingests device events, normalizes, applies rules,
  stores, and fans out alerts

- **Stream Gateway:** converts RTSP to browser-friendly streams (WebRTC,
  or HLS and LL-HLS as fallback) using a media server such as MediaMTX
  or go2rtc

- **Rules and Notification Service:** severity, schedules, escalation,
  WhatsApp (provider adapters), email, push

- **Report Service:** aggregates data, renders DOCX and PDF, schedules
  and delivers

- **Auth and Admin Service:** users, roles, audit, tenants

- **API Gateway** exposing REST and WebSocket (real-time events) to the
  frontend

<!-- -->

- **AI workers:** Separate workers using ONNX Runtime with NVIDIA
  TensorRT and CUDA (primary) or OpenVINO on Intel CPUs and Arc GPUs
  (alternative), decoding with FFmpeg (NVDEC on NVIDIA, VA-API on
  Intel). They pull sub-streams from the gateway, run Tier S analytics,
  face and plate recognition, and publish normalized events. They scale
  out as extra nodes. NVIDIA drivers and CUDA are free to use but closed
  source, so they are a declared exception: install them from the
  distribution or NVIDIA's own repository, pin the versions, and do not
  redistribute them inside our product.

- **GPS service:** Traccar, feeding positions to the platform for
  PostGIS geofence evaluation (5.11).

- **License service:** Small separate service built in-house with
  open-source cryptography, operated by you, with offline-verifiable
  signed license files (5.12).

**Data**

- Relational database (PostgreSQL, with PostGIS for geo features) for
  devices, events, incidents, users, reports

- PostgreSQL also provides queues and real-time notifications
  (LISTEN/NOTIFY with a queue library). **Redis is dropped** because its
  current license is not open source; Valkey (BSD) is the fallback if a
  cache is ever needed.

- Local filesystem storage behind a storage interface for snapshots,
  clips and generated reports, with optional S3-compatible storage (for
  example SeaweedFS, Apache 2.0). **MinIO is not used:** plain
  filesystem storage is simpler and has no license obligations.

**Frontend**

- Web app (React or Next.js with TypeScript), responsive, with a
  dedicated **Wall mode** (kiosk) for the 32-channel grids and the
  rotating 4-camera screen

- Map component (Leaflet or MapLibre) with self-hosted
  OpenStreetMap-based map tiles (OpenMapTiles or Protomaps), credited to
  OpenStreetMap. Paid map services such as Google Maps or Mapbox are not
  used. Floor plans are uploaded images.

**Deployment**

- Docker Engine or Podman with Compose for single-server installs, with
  k3s (Apache 2.0) as a path to Kubernetes for larger deployments

- Caddy or Nginx reverse proxy with TLS from Let's Encrypt or an
  internal certificate authority (step-ca), centralized logging, health
  checks, a built-in health dashboard and a Prometheus metrics endpoint.
  Grafana may be used internally by the IT Team but is not bundled
  (AGPL).

- Server: Linux (Debian or Ubuntu Server LTS) delivered as an installer
  script, a VM image (KVM or Proxmox VE) or a Docker Compose package,
  plus a backup Windows installer that runs the same stack in WSL2
  (5.12).
  Wall PCs: Windows installer (.exe) or a Linux package (see 5.12).

**Suggested stack (free and open source apart from declared exceptions;
AI may propose alternatives with reasons):** Debian or Ubuntu Server
LTS; Python (FastAPI) backend so the API and AI workers share one
language; PostgreSQL + PostGIS (also used for queues); MediaMTX or
go2rtc; React + TypeScript + Tailwind; ONNX Runtime with TensorRT on
NVIDIA GPUs (OpenVINO on Intel as alternative); Traccar for GPS;
WeasyPrint for PDF; python-docx for Word; WireGuard for links to other
subnets; Docker Engine or Podman; NSIS and a Go Wall Agent for the Windows wall
PC installer.

## 8. Core Data Model (Initial Sketch)

- **Tenant / Client** (id, name, logo, colors, default language,
  timezone, deployment mode: on-premises or hosted)

- **Site** (id, tenant, name, address, lat, lon)

- **NVR** (id, site, model, IP, firmware, channels, status, credentials
  ref)

- **Camera** (id, NVR, channel, name, lat, lon, bearing, fov, zone,
  capabilities, status, recognition qualified: face, plate)

- **Zone / Geofence** (id, site, type, polygon, schedule, rules)

- **Event** (id, source device, camera, type, severity, timestamp,
  confidence, snapshot ref, clip ref, geotag, raw payload)

- **Incident** (id, events, status, assignee, notes, evidence)

- **Alert Rule** (conditions, schedule, severity, channels, escalation)

- **Report** (id, type, period, files, delivery status)

- **Recipient** (name, role, WhatsApp number, opt-in, report
  subscriptions)

- **User / Role / Audit Log**

<!-- -->

- **Network Segment** (id, site, CIDR, access method, collector agent
  ref)

- **Analytics Profile** (channel, tier E/N/S, enabled rules, worker
  assignment)

- **Watchlist / Person / Face Template / Plate / Vehicle** (tenant, list
  type, consent and retention fields)

- **GPS Asset and Guard** (tracker id, type, assigned zones, last
  position)

- **Evidence Item** (incident, source clip, checksum, retention date)

- **Wall Node and Layout** (node, monitors, assigned grid or rotation
  set)

- **Report Template and Delivery Log** (branding, schedule, recipient,
  delivery status)

- **License** (tenant, site, NVR or channel ceiling, feature flags,
  perpetual or expiry date, signature)

- **Site Connector** (site, WireGuard peer, last seen; hosted option
  only)

## 9. UX and UI Direction

- **Design feel:** Calm, high-contrast, control room style. Dark theme
  default. Status colors consistent: green (healthy), amber (warning),
  red (critical), grey (offline).

- **Key screens:**

  1.  Wall screens: one per NVR (32-channel grid), plus the rotating
      4-camera screen

  2.  Operator dashboard: live alert feed, health summary, map

  3.  Site map and floor plan view with cameras and geofences

  4.  Alert and incident center

  5.  Playback and evidence search

  6.  Reports center (generate, preview, download, send to WhatsApp)

  7.  Device management and onboarding wizard

  8.  Rules, schedules, and geofence editor

  9.  Users, roles, audit logs, system settings

  10. Wall node and layout manager, and analytics coverage view

  11. Watchlists (faces and plates) with enrollment and match review

  12. GPS map for vehicles and guards, and tenant and license
      administration

- **Principles:** Video first, minimal chrome, two clicks from alert to
  footage, fully usable with keyboard, readable from a distance on large
  monitors.

## 10. Delivery Phases (Proposed)

| **Phase**                   | **Outcome**                                                                                                                       | **Builder review point**                                 |
|-----------------------------|-----------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------|
| 0\. Discovery and PoC       | Hardware inventory, channel mix by tier, compatibility matrix, PoC on real devices (see Section 20)                               | PoC go or no-go, requirements sign-off                   |
| 1\. Foundation              | Repo, environments, tenant-ready schema, auth, device adapter (ISAPI, ONVIF, RTSP), network segments, health monitoring           | Demo adding an NVR and seeing its channel list and tiers |
| 2\. Live Viewing            | 32-channel NVR screens, 4-camera rotation loop, Wall Agent with Windows installer and Linux package, layouts                      | Test on real wall PCs and monitors at 6 NVRs             |
| 3\. Edge Events and Alerts  | Event ingestion and normalization, rules, alerts, snapshots, clips, evidence vault                                                | Trigger real events and verify alerts                    |
| 4\. Server AI Engine        | Tier S workers for non-AI cameras on NVIDIA GPUs with TensorRT (OpenVINO alternative), image-quality checks, GPU benchmarking     | Person and vehicle detection on a non-AI camera          |
| 5\. Geo Features            | Geotagging, self-hosted maps, camera zones, Traccar GPS geofences, guard tracking                                                 | Walk-through of zone and vehicle breach scenarios        |
| 6\. Reporting and Delivery  | Daily, weekly, monthly reports in DOCX and PDF, WhatsApp provider adapters with email and ntfy fallback, role-based subscriptions | Review sample reports with the client                    |
| 7\. Face and Plate          | Watchlists, edge and open-source server recognition, review workflow, legal gate cleared                                          | Accuracy results on client footage, legal sign-off       |
| 8\. Hardening and Licensing | RBAC, 2FA, audit, backups, in-house license service, performance and security testing, license scan                               | Security checklist, load test at 20 NVR scale            |
| 9\. Bundling and Deployment | Linux server installer script and VM image, Windows wall PC installer, documentation, training, pilot go-live                     | Client acceptance                                        |
| 10\. Growth                 | Remaining Section 5.8 items and new ideas (see Section 20)                                                                        | Prioritization session                                   |

## 11. Definition of Done (Per Feature)

- Meets acceptance criteria written before coding

- Code reviewed, tested (unit and integration), and linted

- Works against real Hikvision hardware or a documented simulator

- Documented (API, user, admin) and security-checked

- Demonstrated to the builder and approved

<!-- -->

- Tested on each camera class it touches (edge AI, NVR-assisted, non-AI)

- New dependencies pass the free and open-source policy (Section 19) and
  are listed in the SBOM

## 12. Open Questions and Assumptions

**Builder answers (from the revised document) with AI recommendations
and design impact.** Update this table as items change.

| **Question**                  | **Builder answer**                                                                                                                           | **Recommendation and design impact**                                                                                                                                    |
|-------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Scale and models              | 6 NVRs, scaling to 10 and 20. Must support all Hikvision NVR and camera models. NVR model on site: DS-7632NXI-K2/16P (v0.5). | Design for 640 channels. Device adapter layer (ISAPI, ONVIF, RTSP) and a compatibility matrix per model and firmware. The PoE ports put cameras behind the NVR (Section 7). Sizing in Sections 17 and 18. |
| Network layout                | One subnet now; room for more subnets later.                                                                                                 | Add a Network Segment entity and optional collector agents. No hard-coded IP assumptions.                                                                               |
| Hikvision platform licenses   | No HikCentral or Hik-Connect. Build on open-source.                                                                                          | Confirmed. Direct device APIs only. ISUP dropped. Policy in Section 19.                                                                                                 |
| Geofencing                    | Both camera-based and GPS-based.                                                                                                             | Platform owns geofences. Camera zones pushed via ISAPI where possible. GPS via Traccar and PostGIS (5.11).                                                              |
| Installed cameras             | Mix of ColorVu, AcuSense and non-AI cameras.                                                                                                 | Edge first, server assisted. Three analytics tiers (5.9). Open-source AI workers on NVIDIA GPUs for non-AI cameras.                                                     |
| Face and plate recognition    | Yes, required, on most cameras (v0.5).                                                                                                       | Watchlist based, open-source models only, per-camera qualification test. **Conflict:** general cameras rarely meet the face size needed, broad coverage raises GPU cost and legal risk (5.10). Legal gate before go-live. |
| Hosting, server and wall PCs  | On-premises and hosted. Windows installer for wall PCs, and for the server as a backup (v0.5). NVIDIA accepted. Three wall PCs exist: Core i5, 16 GB RAM, 55 inch Hisense TVs. | Linux server with NVIDIA GPUs (Section 17); Windows server backup through WSL2 (5.12). Seven screens at 6 NVRs need a fourth wall PC or three TVs on one PC; the PoC decides. |
| WhatsApp                      | Client registers the number. Recipients: management, CSO, IT Manager. No licensing or paid solutions. Provider A chosen (v0.5).               | Free self-hosted gateway with email and ntfy fallback (5.7). Number, recipient phones and send times still needed. |
| Retention and backup          | 30 days, with backup to an external drive. Builder chose 4 x 8 TB drives per NVR (v0.5).                                                    | **Conflict:** the DS-7632NXI-K2/16P has 2 drive bays, so 4 drives do not fit. Options in Section 18. External backup (restic or BorgBackup) covers evidence, database and configuration, not all video (5.13). |
| Branding, languages, timezone | Make them selectable and uploadable (v0.5).                                                                                                  | Logo upload, color picker, language and timezone selection per tenant and per user. Defaults: English, Africa/Lagos, timestamps stored in UTC. |
| Single client or product      | Multi-tenant with licensing: per site, perpetual, license service run by the builder (v0.5).                                                | Tenant-ready from day one; on-premises first, hosted option with site connectors (5.12). |
| Internet reliability          | Highly reliable.                                                                                                                             | Enables free Let's Encrypt certificates, email and optional off-site backup. Still design for offline tolerance.                                                        |

**Open questions still waiting (v0.5):**

- **NVR drives (Conflict):** the NVR has 2 bays. Choose between 2 larger
  drives (if the firmware accepts them), lower bitrates with H.265+, a
  4 or 8 bay NVR, or fewer than 30 days on low-value cameras (Section 18).
- **Recognition coverage (Conflict):** accept per-camera qualification
  (5.10), and confirm the extra GPU budget it may need (Section 17).
- Are all six NVRs the DS-7632NXI-K2/16P, and on which firmware? The
  probe (Section 15) will answer this.
- WhatsApp: the dedicated number, recipient phone numbers and preferred
  send times.
- Which lawyer or data protection officer will review biometric
  processing?
- Quotes for the GPU server, drives, UPS units and any fourth wall PC.
- Which Windows edition runs on the wall PCs (Windows 11 Pro assumed)?
- Which hosting provider and region for the hosted option?
- Which open-source license do we publish our own code under? Apache 2.0
  is suggested.

**Answered in v0.5:** NVR model; wall PCs and displays; GPS start (10
Android phones, open protocols); licensing (per site, perpetual, run by
the builder); deployment (on-premises and hosted); branding, language and
timezone (selectable and uploadable); Windows server installer (yes, as a
backup); default WhatsApp provider (Provider A).

**Working assumptions (confirmed by the builder):**

- Cameras and NVRs support ISAPI and RTSP and are reachable from the
  platform server.

- A server with adequate CPU, RAM and storage will be provided, to the
  specifications in Section 17.

- Web-based delivery is acceptable for the control room, with kiosk-mode
  browsers on the wall screens.

- WhatsApp delivery uses a pluggable provider. The default depends on
  the builder's decision in Section 12 (free self-hosted gateway or the
  official paid Cloud API).

**Additional assumptions (confirmed by the builder in v0.5):**

- Camera sub-streams can be set to H.264 so every browser can decode
  them.

- Roughly 60 or fewer channels per NVIDIA GPU need server-side analytics
  at about 5 frames per second (about 30 per Intel or AMD accelerator).
  The PoC benchmark and the real channel mix will replace this.

- NVRs are on a gigabit network and the server has 10 GbE once the
  deployment reaches 10 NVRs.

## 13. Risks to Watch

- Browser playback of RTSP requires a gateway, and 32 simultaneous
  streams per screen can overload weak client PCs. Mitigation:
  sub-streams, hardware decoding, and limit frame rate.

- Differences in firmware across Hikvision models may change ISAPI
  behavior. Mitigation: capability discovery and a device compatibility
  matrix.

- Face and plate data raise legal and privacy exposure. Mitigation:
  explicit client sign-off, access controls, and retention limits.

- If the official Cloud API is used, template approval and number
  verification take time and messages are charged. The free self-hosted
  gateway is unofficial and the number could be restricted. Mitigation:
  dedicated number, low volume, session health checks and automatic
  email fallback.

- Default Hikvision credentials and exposed devices are a common attack
  vector. Mitigation: hardening checklist as part of onboarding.

- Scope creep from the growing feature list. Mitigation: prioritize with
  a MoSCoW list and phase gates.

<!-- -->

- Server-side AI load and accuracy on non-AI cameras may exceed one GPU.
  Mitigation: GPU benchmark in the PoC, sub-stream detection at low
  frame rates, adding GPUs or AI nodes, and replacing critical non-AI
  cameras with AcuSense models.

- Face and plate accuracy on local conditions (lighting, angles, plate
  formats) is unknown. Mitigation: measure on client footage and use
  human confirmation.

- License traps (source-available, non-commercial model weights or
  datasets, freemium tools with paid tiers) can break the free and
  open-source rule. Mitigation: Section 19 policy and a scan every
  release.

- Windows wall PCs can restart for updates, change drivers or differ in
  video decoding. Mitigation: Wall Agent watchdog, a scheduled update
  window set by the IT Team, testing on the real wall PC model for 24
  hours, and a Linux wall PC image as fallback.

- NVIDIA driver, CUDA and TensorRT version mismatches can break the AI
  workers after an update. Mitigation: pin versions, test updates on a
  staging server before production, and keep OpenVINO on Intel as a
  fallback path.

- NVRs limit concurrent streams and outgoing bandwidth, and wall PCs
  limit decoding. Mitigation: pull each stream once, use sub-streams,
  add wall nodes, and measure in the PoC.

- Multi-tenant data leakage. Mitigation: tenant_id everywhere, row-level
  security, per-tenant storage paths and automated isolation tests.

- Older Hikvision firmware has had serious security flaws. Mitigation:
  firmware update policy, isolated camera VLAN, no port forwarding of
  cameras or NVRs, and no default passwords.

- NVR storage: two drive bays may not hold 30 days for 32 cameras.
  Mitigation: measure real bitrates with the probe, use H.265+, capped
  bitrate and event recording on low-value cameras, or move to a 4 or 8
  bay NVR (Section 18).

- Broad face and plate recognition may cost more GPUs than planned and
  may not pass the legal review. Mitigation: per-camera qualification,
  GPU benchmark with recognition load, and early legal review.

- The hosted option sends site data across the internet. Mitigation:
  WireGuard site connectors, no inbound ports at the site, encryption at
  rest, and a hosting region that satisfies the NDPA.

- Power loss can corrupt databases and stop recording. Mitigation: UPS
  with graceful shutdown for the server, wall PCs and NVRs, and
  auto-start after power returns.

## 14. Decision Log (Update After Each Session)

| **Date**   | **Decision**                                                                                                                           | **Reason**                                           | **Decided by**                         |
|------------|----------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------|----------------------------------------|
| 2026-10-21 | No HikCentral or Hik-Connect; open-source based                                                                                        | Avoid license cost and lock-in                       | Builder                                |
| 2026-10-21 | Scale to 6, then 10, then 20 NVRs (640 channels)                                                                                       | Client growth plan                                   | Builder                                |
| 2026-10-21 | Geofencing covers camera zones and GPS                                                                                                 | Client requirement                                   | Builder                                |
| 2026-10-21 | Face and plate recognition required                                                                                                    | Client requirement                                   | Builder                                |
| 2026-10-21 | Multi-tenant licensed product                                                                                                          | Commercial plan                                      | Builder                                |
| 2026-10-21 | All Section 5.8 features are in scope                                                                                                  | Builder instruction                                  | Builder                                |
| 2026-10-21 | Free and open-source stack, with declared exceptions (Section 19)                                                                      | Builder instruction (v0.3, refined in v0.4 and v0.5) | Builder                                |
| 2026-10-21 | Windows installer (.exe) provided for wall PCs; server stays on Linux                                                                  | Builder requirement for wall PCs                     | Builder                                |
| 2026-10-21 | NVIDIA GPUs accepted as the primary AI path; Intel OpenVINO kept as alternative                                                        | Drivers and CUDA are free; only hardware costs money | Builder                                |
| 2026-10-21 | Edge first, server assisted AI with three tiers                                                                                        | Non-AI cameras are present                           | Builder (approved 2026-10-28)          |
| 2026-10-21 | WhatsApp through pluggable providers; free self-hosted gateway by default with email fallback                                          | WhatsApp has no free official route                  | Builder (approved 2026-10-28)          |
| 2026-10-21 | SMS dropped; push via self-hosted ntfy; self-hosted OpenStreetMap tiles                                                                | Avoid paid services                                  | Builder (approved 2026-10-28)          |
| 2026-10-21 | Drop Redis and MinIO; PostgreSQL for queues, filesystem for storage                                                                    | License risk and fewer moving parts                  | Builder (approved 2026-10-28)          |
| 2026-10-21 | Traccar for GPS; platform owns geofences                                                                                               | Avoid rebuilding tracker protocols                   | Builder (approved 2026-10-28)          |
| 2026-10-21 | Release plan 1.0, 1.1 and 2.0                                                                                                          | Deliver the first client sooner                      | Builder (approved 2026-10-28)          |
| 2026-10-28 | NVR drives: 4 x 8 TB per NVR                                                                                                           | Builder choice                                       | Builder; **Conflict**: model has 2 bays (Section 18) |
| 2026-10-28 | Provider A (self-hosted open-source WhatsApp gateway) is the default                                                                   | No paid services                                     | Builder                                |
| 2026-10-28 | NVR model on site: DS-7632NXI-K2/16P                                                                                                   | Site inventory                                       | Builder                                |
| 2026-10-28 | Use the 3 existing wall PCs (Core i5, 16 GB) with 55 inch Hisense TVs; add PCs as needed                                               | Reuse existing hardware                              | Builder                                |
| 2026-10-28 | Recognition on most cameras, through a per-camera qualification test                                                                   | Client requirement; image quality limits             | Builder; qualification test Proposed (AI) |
| 2026-10-28 | GPS: 10 Android phones with Traccar Client to start; trackers on open, Traccar-supported protocols                                     | Open standards                                       | Builder                                |
| 2026-10-28 | Licensing per site, perpetual; builder runs the license service                                                                        | Commercial plan                                      | Builder                                |
| 2026-10-28 | Deployment both on-premises and hosted; hosted uses WireGuard site connectors                                                          | Commercial plan                                      | Builder; connector design Proposed (AI) |
| 2026-10-28 | Branding, language and timezone selectable and uploadable per tenant and user                                                          | Multi-tenant product                                 | Builder                                |
| 2026-10-28 | Windows server installer as a backup, running the stack in WSL2 with Docker Engine                                                     | Clients with Windows-only servers                    | Builder; WSL2 design Proposed (AI)     |
| 2026-10-28 | Sub-streams H.264; about 60 channels per GPU; gigabit network with 10 GbE at 10 NVRs                                                   | Working assumptions                                  | Builder                                |
| 2026-10-28 | Wall Agent runs in the signed-in user's session, started and restarted by a scheduled task, instead of a WinSW Windows service           | Windows services cannot show windows (Session 0)     | Proposed (AI)                          |
| 2026-10-28 | Wall Agent written in Go (single .exe for Windows, same code for Linux wall PCs)                                                       | No runtime to install; cross-platform                | Proposed (AI)                          |

## 15. Progress Tracker (Update After Each Session)

- **Current phase:** Phase 0, Discovery and PoC (building)

- **Completed:** Context document v0.1 to v0.5; builder answers to the
  open questions; PoC plan updated to v0.5; Step 0 (Docker Compose
  skeleton: PostgreSQL with PostGIS, API health service, MediaMTX
  stream gateway, Caddy with HTTPS), started and health-checked in the
  build environment; Step 1 (read-only NVR capability probe that writes
  the compatibility matrix, a retention and bandwidth summary and the
  raw ISAPI responses), with 6 passing automated tests on simulated NVR
  data; task 15 (Tier S AI worker: YOLOX on ONNX Runtime, zone rules
  with schedules, normalized events with snapshots stored through the
  API), tested end to end on a sample video at 0.16 to 0.26 s from frame
  to stored event; task 19 (wall capacity test page with a verdict,
  automatic tile reconnect and downloadable results), tested with 32
  tiles in the build environment; task 22 (Wall Agent in Go, Windows
  installer with a scheduled task, platform heartbeats and layouts,
  self-update), tested on Linux with two screens: crash, freeze, outage,
  layout change and self-update all recovered by themselves.

- **In progress:** Running on site: the skeleton on the real server, the
  probe against all six NVRs, task 15 on one non-AI camera, and task 19
  on the existing wall PCs (runs A to C in
  `docs/task-19-wall-capacity-test.md`), and the task 22 soak on one
  Windows wall PC (`docs/task-22-wall-agent.md`).

- **Blocked or waiting on:** Probe results from site; decisions on the
  NVR drive conflict and recognition coverage; dedicated WhatsApp
  number and recipient numbers; legal reviewer for face and plate; GPU
  server quote.

- **Next session goal:** Read the probe, task 15 and task 19 results;
  confirm tiers (task 14); decide on a fourth wall PC; approve the Wall
  Agent design change; then prepare the GPU benchmark (task 16) and the
  WhatsApp gateway test (task 21).

- **Files and repos created:** Repository
  `github.com/striver-star/Smart-Surveillance` (branch main): `compose.yaml`, `services/api`, `gateway/mediamtx.yml`,
  `proxy/Caddyfile`, `db/init`, `tools/probe` (probe and tests),
  `docs/poc-plan-v0.5.md`, `docs/stage-checklist-step0-step1.md`,
  `services/ai-worker` (task 15), `web/wall-test` (task 19),
  `services/wall-agent` (task 22),
  `tools/fetch-models.sh`, `tools/nvr-paths.sh`, and a guide for each
  task in `docs/`.

## 16. Reusable Starter Prompts

**Session opener:**

> You are my AI development partner on the project described in the
> attached context document. I am the IT Manager and will review your
> work at each stage. Today's goal: \[goal\]. First, summarize your
> understanding in three lines and list any assumptions. Then deliver
> the work in small reviewable steps with a verification checklist at
> the end.

**Code generation:**

> Generate complete, production-quality code for \[module\], following
> Section 7 architecture. Include file structure, setup instructions,
> environment variables, tests, and a short explanation of how to verify
> it works with a real Hikvision device.

**UX and UI:**

> Design the \[screen\] from Section 9 for a control room operator.
> Provide layout description, component structure, and the implemented
> frontend code. Prioritize readability on large monitors and speed of
> operator actions.

**Review and risk check:**

> Review the work done so far against Sections 5, 6, and 13. List gaps,
> risks, and recommended next steps in priority order.

**Feature ideation:**

> Based on this context, suggest 10 additional features that would
> increase client value, ranked by impact versus effort, and note any
> dependency on Hikvision device capabilities.

**Free and open-source check:**

> List every third-party library, model, tool and service used so far
> with its license. Flag anything that is proprietary, paid,
> source-available, non-commercial or freemium, and propose a free and
> open-source alternative, following Section 19.

**Session closer:**

> Before we finish, write updated text for Section 14 (Decision Log) and
> Section 15 (Progress Tracker) that I can paste into the context
> document, and list any new open questions.

## 17. Recommended Server Specifications (new in v0.2)

Indicative sizing for the platform server. The NVRs record the video, so
the server stores only events, snapshots, evidence clips, the database
and reports. The heavy work is stream handling and AI. Validate these
numbers with the PoC benchmark before purchase.

| **Item**                      | **Tier 1: 6 NVRs (192 channels)**                                                                                                        | **Tier 2: 10 NVRs (320 channels)**                                       | **Tier 3: 20 NVRs (640 channels)**                                       |
|-------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|--------------------------------------------------------------------------|
| Topology                      | Single server                                                                                                                            | Single server; add a second GPU or node as AI load grows                 | Scale out: core node, 2 to 3 AI worker nodes, database node with replica |
| CPU                           | 12 to 16 cores                                                                                                                           | 24 to 32 cores                                                           | 16 to 24 cores per node                                                  |
| RAM                           | 64 GB (ECC preferred)                                                                                                                    | 128 GB                                                                   | 64 to 128 GB per node                                                    |
| GPU (AI workers, face, plate) | 1 x NVIDIA 16 GB class (for example RTX 4000 Ada or A4000 class); plan 2 if recognition runs on most cameras | 1 to 2 x NVIDIA 16 to 24 GB class (for example L4 or RTX 4000 Ada class); more with broad recognition | 1 GPU per AI node; add nodes for recognition load |
| System and database disks     | 2 x 1 TB NVMe, mirrored                                                                                                                  | 2 x 2 TB NVMe, mirrored                                                  | Database node: 2 x 2 TB NVMe mirrored                                    |
| Evidence and snapshots        | 8 TB usable                                                                                                                              | 16 TB usable                                                             | 32 TB or more usable (NAS running open-source software)                  |
| Network                       | 2 x 1 GbE minimum; 10 GbE recommended                                                                                                    | 10 GbE required                                                          | 10 GbE, 25 GbE for the core; non-blocking switches                       |
| Wall PCs (separate)           | 3 existing Core i5 PCs with 55 inch Hisense TVs; 7 screens need a 4th PC or 3 TVs on one PC                                             | 6 PCs for 11 screens                                                     | 11 PCs for 21 screens                                                    |
| OS and power                  | Debian or Ubuntu Server LTS on the server; NVIDIA driver from the repository; UPS with graceful shutdown; auto-start after power returns | Same                                                                     | Same                                                                     |

- **Wall PCs:** Plan one per 2 monitors (64 tiles): modern 8-core CPU
  with Intel integrated graphics or a discrete GPU for hardware decoding
  (D3D11 on Windows, VA-API on Linux), 16 GB RAM, Windows 11 Pro or
  Linux, and Chromium or Firefox in kiosk mode. The Windows license
  comes with the PC hardware. The PoC bake-off sets the real number.

- **Sizing assumptions:** About 60 channels per NVIDIA GPU need
  server-side analytics at roughly 5 frames per second on sub-streams
  (about 30 per Intel or AMD accelerator), and recognition runs on 10 to
  20 gate cameras at most. The v0.5 choice of recognition on most
  cameras makes the load heavier: the PoC benchmark measures channels
  per GPU with recognition switched on, and the GPU count follows from
  that. If the real mix is heavier, add GPUs or replace critical non-AI
  cameras. Benchmark before purchase.

- **Bandwidth:** Roughly 1 Mbps per sub-stream into the gateway, so
  about 192, 320 and 640 Mbps at 6, 10 and 20 NVRs, plus main streams
  for the rotation screen and AI workers. This is why 10 GbE is needed
  from Tier 2.

- **Hardware note:** Servers, GPUs, drives, wall PCs and UPS units are
  hardware purchases. NVIDIA drivers and CUDA are free to use, and
  Windows on the wall PCs is licensed with the hardware, so neither adds
  a software cost to the project. Intel Arc GPUs with OpenVINO and AMD
  GPUs are alternatives if NVIDIA is unavailable.

## 18. NVR Storage Sizing for 30 Days (new in v0.2)

Formula: storage per channel per day in GB is about 10.8 times the
average bitrate in Mbps. Multiply by 30 days and by 32 channels per NVR,
then add 15 percent headroom for overhead and bitrate peaks. The figures
below assume continuous recording with H.265.

| **Camera profile** | **Per channel, 30 days** | **Per 32-channel NVR** | **With 15% headroom** | **Notes**                         |
|--------------------|--------------------------|------------------------|-----------------------|-----------------------------------|
| 2 MP, 2 Mbps       | 648 GB                   | 20.7 TB                | 23.8 TB               | Typical basic camera              |
| 4 MP, 3 Mbps       | 972 GB                   | 31.1 TB                | 35.8 TB               | Common AcuSense class             |
| 4 MP, 4 Mbps       | 1.3 TB                   | 41.5 TB                | 47.7 TB               | High quality setting              |
| 8 MP, 6 Mbps       | 1.9 TB                   | 62.2 TB                | 71.5 TB               | Needs larger NVR or lower bitrate |

- **Site NVR (v0.5):** The DS-7632NXI-K2/16P has **2 drive bays**, no
  RAID, and a 256 Mbps incoming bandwidth limit. The builder's choice of
  4 x 8 TB drives therefore does not fit (**Conflict**). The table shows
  the highest average bitrate per camera that still gives 30 days for 32
  cameras, with 15% headroom:

  | Drives in the 2 bays | Raw capacity | Highest average bitrate per camera for 30 days |
  |---|---|---|
  | 2 x 8 TB | 16 TB | about 1.3 Mbps |
  | 2 x 10 TB | 20 TB | about 1.7 Mbps |
  | 2 x 16 TB (only if the firmware accepts it) | 32 TB | about 2.7 Mbps |

- **Options for the builder:** (1) fit the largest drives the NVR
  firmware accepts (published figures disagree between 10, 16 and 20 TB
  per bay, so check on the device) and use H.265+ with capped bitrate;
  (2) record low-value cameras on events only; (3) move 32-camera sites
  to a 4 or 8 bay NVR from the same range, where 4 x 8 TB or 8 x 8 TB
  fits; (4) accept fewer than 30 days on low-value cameras. The probe
  reports each NVR's real bitrates and estimated retention days, so the
  decision can be made on measured numbers.

- **Drive type:** Use drives rated for 24/7 recording (for example WD
  Purple Pro or Seagate SkyHawk). Without RAID, a failed drive loses its
  share of the footage; the platform's drive health alerts give early
  warning.

- **Check per model:** number of drive bays (many 32-channel NVRs have
  8, some have 16), maximum drive size per bay, RAID support, and
  maximum incoming bandwidth (the sum of all camera bitrates must stay
  below it).

- **Reduce storage safely:** Use H.265 or H.265+, capped variable
  bitrate, and event-based recording on low-value cameras. Keep
  continuous recording on gates, entrances and critical areas.

- **Mixed estates:** Calculate per camera, not per NVR. Take each
  channel's real bitrate from the discovery script, sum them, and size
  drives from the total.

- The platform monitors drive health (SMART where exposed), free space
  and recorded days per channel, and alerts the IT Team before retention
  is at risk.

## 19. Free and Open-Source Policy (updated in v0.5)

Rule from the builder: use free and open-source software. Nothing in the
product may require a paid license, subscription or proprietary software
that we have to buy, apart from the declared exceptions below. Licenses
and terms change, so verify each component when adopting it and record
the result in the SBOM. This is engineering guidance, not legal advice.

**Allowed licenses:** MIT, BSD, Apache 2.0, ISC, MPL 2.0 and similar
permissive licenses; LGPL when used as a separate process or library;
GPL and AGPL only for separate, unmodified services or internal IT tools
that we do not bundle into the product.

**Not allowed:** freemium tools that need a paid tier, source-available
licenses (for example SSPL or RSAL), non-commercial model weights or
datasets, and services billed per use or per month.

**Declared exceptions:**

- The existing Hikvision NVRs, cameras and firmware, which the client
  already owns and which we only talk to through their APIs.

- WhatsApp itself, an external messaging network (see 5.7).

- NVIDIA drivers, CUDA and TensorRT: free to use with no license fee,
  but closed source. Install them from official sources, pin versions,
  and do not redistribute them inside our product. Check NVIDIA's
  current terms before shipping them in any image.

- Windows on the wall PCs: the operating system license comes with the
  PC hardware. Our wall software (Wall Agent and installer) is open
  source, and no extra Windows software is purchased.

- Windows on a server, only for the backup Windows install path
  (5.12), and only when the Windows license already comes with the
  server. No Windows Server license is bought for the product.

- Hosting infrastructure (a rented server or cloud instance) for the
  hosted option. Like hardware, it is paid for by the client; only free
  and open-source software runs on it.

- Physical hardware such as servers, GPUs, wall PCs and drives.

**Approved stack**

| **Layer**                 | **Component**                                                                              | **License**                                           |
|---------------------------|--------------------------------------------------------------------------------------------|-------------------------------------------------------|
| Server operating system   | Debian or Ubuntu Server LTS (no paid support needed)                                       | Free software                                         |
| Wall PC operating system  | Windows 11 (declared exception) or Debian or Ubuntu                                        | Licensed with hardware; free software                 |
| Containers                | Docker Engine or Podman; k3s optional                                                      | Apache 2.0                                            |
| Database                  | PostgreSQL with PostGIS (separate service)                                                 | PostgreSQL License; GPL-2.0 or later                  |
| Backend                   | Python, FastAPI, Uvicorn                                                                   | PSF, MIT, BSD                                         |
| Streaming and decode      | MediaMTX, go2rtc, FFmpeg (LGPL build) with NVDEC or VA-API                                 | MIT, LGPL                                             |
| AI inference              | ONNX Runtime with TensorRT on NVIDIA (declared exception); OpenVINO on Intel; OpenCV       | MIT, Apache 2.0; NVIDIA freeware                      |
| Detection models          | YOLOX or RT-DETR                                                                           | Apache 2.0                                            |
| Face recognition          | OpenCV YuNet (detection) and SFace (recognition)                                           | MIT, Apache 2.0                                       |
| Plate recognition         | YOLOX or RT-DETR detector with PaddleOCR                                                   | Apache 2.0                                            |
| Optional analytics engine | Frigate (PoC evaluation)                                                                   | MIT                                                   |
| GPS                       | Traccar                                                                                    | Apache 2.0                                            |
| Frontend                  | React, TypeScript, Tailwind CSS                                                            | MIT, Apache 2.0                                       |
| Maps                      | Leaflet or MapLibre GL JS with self-hosted OpenStreetMap tiles (OpenMapTiles or Protomaps) | BSD; map data under ODbL with credit to OpenStreetMap |
| Reports                   | WeasyPrint (PDF), python-docx (Word), Matplotlib (charts)                                  | BSD, MIT, BSD-style                                   |
| Web server and TLS        | Caddy or Nginx, Let's Encrypt, step-ca                                                     | Apache 2.0, BSD, free service                         |
| Authentication            | pyotp for two-factor codes; Keycloak optional                                              | MIT, Apache 2.0                                       |
| Our license service       | libsodium or Python cryptography                                                           | ISC, Apache 2.0 or BSD                                |
| Notifications             | Any SMTP server (for example Postfix), ntfy, WhatsApp gateway (whatsapp-web.js or Baileys) | Open source; see 5.7 for gateway risk                 |
| Wall PC installer         | NSIS installer, Wall Agent (our code, Go), Windows Task Scheduler                           | zlib, BSD (Go), ours                                  |
| Wall PC browser           | Chromium or Firefox in kiosk mode                                                          | BSD-style; MPL 2.0                                    |
| Monitoring                | Prometheus; Grafana for internal IT use only                                               | Apache 2.0; AGPL                                      |
| Backup and links          | restic or BorgBackup, rsync, WireGuard, chrony                                             | BSD, GPL (separate tools)                             |
| Development               | Git with Forgejo (self-hosted), pytest, Playwright, ruff, ESLint, MkDocs                   | Open source                                           |
| SBOM and license scan     | Syft, ScanCode Toolkit, pip-licenses                                                       | Apache 2.0, MIT                                       |

**Excluded and replaced**

| **Not used**                              | **Why**                                          | **Free and open-source replacement**                                                  |
|-------------------------------------------|--------------------------------------------------|---------------------------------------------------------------------------------------|
| Docker Desktop; buying Windows Server licenses | Licensed or paid terms                         | Docker Engine (in WSL2 for the backup Windows server path); Linux remains the primary server |
| Google Chrome and Microsoft Edge on walls | Proprietary                                      | Chromium or Firefox                                                                   |
| HikCentral and Hik-Connect                | Proprietary and licensed                         | Direct ISAPI, ONVIF and RTSP                                                          |
| Redis (current versions)                  | Not an open-source license                       | PostgreSQL queues; Valkey (BSD) if a cache is needed                                  |
| MinIO                                     | AGPL obligations, not needed                     | Filesystem storage; SeaweedFS (Apache 2.0) optional                                   |
| Ultralytics YOLO                          | AGPL, commercial license needed for products     | YOLOX or RT-DETR                                                                      |
| InsightFace pretrained models             | Non-commercial terms                             | OpenCV YuNet and SFace; train only on permissively licensed data                      |
| Google Maps, Mapbox                       | Paid and proprietary                             | Self-hosted OpenStreetMap tiles                                                       |
| SMS gateways and paid push services       | Per-message fees                                 | Self-hosted ntfy and email                                                            |
| WhatsApp Business Cloud API               | Metered Meta service                             | Self-hosted gateway or email; Cloud API only as an approved exception                 |
| Microsoft Office on servers               | Licensed                                         | Not needed: python-docx creates DOCX; recipients can open it in LibreOffice (MPL 2.0) |
| Paid code-signing certificate             | Annual fee                                       | Not required for IT-managed wall PCs; optional exception if wanted                    |

- Generate a software bill of materials (SBOM) and run a license scan on
  every release.

- No new dependency, model, dataset or service is added without
  recording its license and confirming it is free and open source or a
  declared exception.

- Model weights and training datasets are dependencies too and need the
  same check.

## 20. Release Plan and PoC Adjustments (new in v0.2)

Because every Section 5.8 feature is now in scope, sequencing matters.
This plan keeps the first client go-live achievable (MoSCoW: Must,
Should, Could).

| **Release** | **Priority** | **Contents**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | **Gate**                                    |
|-------------|--------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------|
| 1.0         | Must         | NVR walls and rotation screen with Windows wall PC installer and Wall Agent, device health, edge events and alerts, snapshots and clips, geotagging and self-hosted maps, camera zones with schedules, daily, weekly and monthly reports (DOCX and PDF), WhatsApp delivery through the provider interface with email and ntfy fallback, RBAC, 2FA, audit log, backup and restore, Linux server install, tenant-ready schema and basic license enforcement, basic Tier S analytics for non-AI cameras on NVIDIA GPUs | First client pilot and acceptance           |
| 1.1         | Should       | Face watchlists and plate recognition on qualified cameras (after legal gate), GPS and guard tracking via Traccar (10 Android phones first), evidence vault, escalation, PTZ, smart search, shift logbook, onboarding wizard, VM image, Linux wall PC package, Windows server backup installer (WSL2), hosted option with site connectors                                                                                                                                                                                                                                                                                                      | Accuracy results and legal sign-off         |
| 2.0         | Could        | Anomaly detection, cross-camera correlation, heat maps, false alarm dashboard, access control integration, shared multi-tenant hosted control plane at scale, native mobile app, extra languages                                                                                                                                                                                                                                                                                                                                    | Prioritization session with the client base |

**PoC adjustments needed (the separate PoC plan should be updated):**

- Test one non-AI camera end to end through a Tier S worker, and
  benchmark streams per GPU on NVIDIA with TensorRT, with an Intel
  OpenVINO run for comparison.

- Test device discovery across three camera classes (ColorVu, AcuSense,
  non-AI) and at least two NVR firmware versions.

- Run a face and plate accuracy trial on one entrance camera with real
  client footage, then on a sample of general cameras to set the
  per-camera qualification rule (5.10).

- Measure wall PC capacity with 64 tiles on an existing Core i5 wall PC
  and a 55 inch Hisense TV, including whether one PC can drive three
  TVs, and the NVR connection and bandwidth limits.

- Test the WhatsApp gateway adapter with the dedicated number for a
  week, including the automatic email fallback, to judge how stable it
  is.

- Build a prototype Wall Agent and Windows installer, then run it on the
  real wall PC model with 64 tiles for 24 hours, including a Windows
  restart and a camera outage.

- Run a license scan on the PoC code, models and datasets to confirm
  everything is free and open source.

**Long-lead items to start now:** A dedicated WhatsApp number and the
recipients' phone numbers, legal review of biometric processing, the
probe run on every NVR, quotes for the GPU server, NVR drives, UPS units
and any fourth wall PC, and the hosting provider for the hosted option.

## 21. Change Log (new in v0.2)

**Builder changes captured from the revised document:** all Section 5.8
features marked for integration; Windows .exe single-server install
added; answers supplied to the open questions in Section 12 (scale,
subnets, no HikCentral, both geofence types, camera mix, face and plate
required, WhatsApp recipients, 30 day retention, multi-tenant licensing,
reliable internet); working assumptions confirmed.

**AI changes in v0.2 (the Windows single-server install above was
removed in v0.3 and returns in v0.5 as a backup path through WSL2):**

- Core principle revised to edge first, server assisted, because non-AI
  cameras are present.

- Added Sections 5.9 to 5.13: analytics tiers, face and plate, GPS
  geofencing, multi-tenancy and licensing, evidence and backup.

- Added wall node model, stream pulling and pre-connect rules to 5.1.

- Added WhatsApp recipients, subscriptions and setup notes to 5.7.

- Updated Sections 6, 7, 8, 9, 10 and 11: capacity targets, ONVIF and
  HikCentral decision, Redis and MinIO dropped, AI worker, GPS and
  license services, new data model entities, new screens, revised
  delivery phases, stronger definition of done.

- Rebuilt Section 12 as a table with recommendations; added new risks
  (13); pre-filled the Decision Log (14) and Progress Tracker (15);
  added two starter prompts (16).

- Added Sections 17 to 21 and moved the Glossary to Section 22.

- Corrected typos ("Comfirmed", "windows .exe documentation").

**AI changes in v0.3 (free and open-source only; the Windows and NVIDIA
removals were reversed in v0.4):**

- Added the builder rule: entirely free and open source, with declared
  exceptions only for existing Hikvision devices, WhatsApp itself and
  hardware (Section 19).

- Removed Windows: no Windows installer, server, wall PCs, Docker
  Desktop or code-signing certificate. Linux only.

- Replaced the NVIDIA GPU path with Intel (OpenVINO) or AMD, rebuilt the
  server specifications in Section 17 and halved the per-accelerator
  channel assumption until benchmarked.

- Changed WhatsApp to a pluggable provider with a free self-hosted
  gateway as default, the official Cloud API as an optional paid
  exception, and free email and ntfy fallback. This overrides the
  earlier confirmed assumption that the Cloud API would be used, and
  needs your decision.

- Dropped SMS, added self-hosted ntfy push, and added self-hosted
  OpenStreetMap map tiles instead of paid map services.

- Rebuilt Section 19 as a full approved stack and an
  excluded-and-replaced list.

- Updated Sections 1, 3, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17 and 20
  to match.

**Builder changes in v0.4:** a Windows installer is still required for
the wall PCs, and NVIDIA is accepted because it costs only the hardware.

**AI changes in v0.4:**

- Added a Windows wall PC installer (Wall Agent as a Windows service,
  built with NSIS and WinSW, kiosk Chromium or Firefox). The server
  stays on Linux; the earlier Windows server installer remains out of
  scope.

- Restored NVIDIA GPUs as the primary AI path with ONNX Runtime and
  TensorRT, kept Intel OpenVINO as an alternative, and restored the
  Section 17 server specifications and the 60 channels per GPU estimate.

- Redefined the policy in Section 19 with declared exceptions: Hikvision
  devices, WhatsApp itself, NVIDIA drivers and CUDA, and Windows on wall
  PCs.

- Updated Sections 1, 3, 5.1, 5.9, 5.12, 7, 10, 12, 13, 14, 15, 17, 19
  and 20, plus the release plan, risks and PoC adjustments.

**Builder changes in v0.5:** approved every Proposed decision; chose
Provider A for WhatsApp; named the NVR model (DS-7632NXI-K2/16P); chose
4 x 8 TB drives per NVR; described the wall PCs (3 existing Core i5 PCs,
16 GB RAM, 55 inch Hisense TVs); asked for recognition on most cameras;
chose 10 Android phones and open protocols for GPS; set licensing per
site and perpetual, run by the builder; chose both on-premises and
hosted deployment; asked for selectable and uploadable branding,
language and timezone; asked for a Windows server installer as a backup;
confirmed the AI's pending assumptions; asked to start building.

**AI changes in v0.5:**

- Recorded the builder's answers in Sections 1, 3, 5.1, 5.6, 5.7, 5.10,
  5.11, 5.12, 7, 8, 12, 14, 17, 18, 19 and 20.
- Flagged three conflicts: the NVR has 2 drive bays (Section 18);
  recognition on most cameras meets image-quality, GPU and legal limits
  (5.10); seven screens need a fourth wall PC or three TVs on one PC
  (5.1).
- Added the PoE note (cameras behind the NVR), the hosted option with
  WireGuard site connectors, the Windows server backup path through
  WSL2, and three new risks.
- Updated the Progress Tracker for the start of building and added
  Section 23, the master task list.
- Task 22: revised the Wall Agent design (scheduled task in the user's
  session instead of a WinSW Windows service, agent written in Go) in
  5.12, Section 14 and Section 19.

## 22. Glossary

- **NVR:** Network Video Recorder

- **ISAPI:** Hikvision's HTTP-based device API

- **ISUP (EHome):** Hikvision protocol for device-to-platform
  connectivity, useful behind NAT

- **RTSP:** Real Time Streaming Protocol for video streams

- **Sub-stream / Main stream:** Low-resolution versus full-resolution
  video feed

- **Geofence:** A virtual boundary that triggers an action when crossed

- **Geotag:** Geographic coordinates attached to a device, event, or
  media file

- **PTZ:** Pan, tilt, zoom camera

- **RBAC:** Role-based access control

- **ANPR:** Automatic number plate recognition

- **PWA:** Progressive web app

<!-- -->

- **Tier E, N, S:** Analytics running on the Edge camera, on the NVR, or
  on our Server AI workers

- **Wall node:** A PC (Windows or Linux) running the Wall Agent and a
  kiosk browser that drives one or two wall monitors

- **ONVIF:** Open standard for IP camera interoperability

- **ColorVu:** Hikvision imaging technology for full-time color video at
  night

- **AcuSense:** Hikvision camera and NVR analytics for human and vehicle
  classification

- **Traccar:** Open-source GPS tracking server

- **NDPA:** Nigeria Data Protection Act 2023

- **DPIA:** Data protection impact assessment

- **SBOM:** Software bill of materials

- **MoSCoW:** Must, Should, Could, Won't prioritization

- **FOSS:** Free and open-source software

- **Wall Agent:** Small open-source program on each wall PC that starts
  the kiosk browsers, syncs layouts, restarts frozen screens, reports
  health and updates itself

- **TensorRT:** NVIDIA runtime for fast AI inference on NVIDIA GPUs
  (free to use, closed source)

- **NSIS:** Open-source tool used to build the Windows installer

- **OpenVINO:** Open-source toolkit for running AI models on Intel CPUs
  and GPUs

- **VA-API:** Open Linux interface for hardware video decoding

- **ntfy:** Open-source push notification service you host yourself

- **WSL2:** Windows Subsystem for Linux, which runs a real Linux system
  inside Windows; used for the backup Windows server install

- **Site connector:** Small service at a client site that links the
  local NVRs to the hosted platform over WireGuard

## 23. Master Task List (Update After Each Session)

Status key: **Done**, **Answered**, **In progress**, **Waiting** (on the
builder or the site), **Conflict** (needs a builder decision), **To do**.
Numbers stay fixed between versions so sessions can refer to them.

**Stage A: Decisions and long-lead items**

1. Approve the Proposed decisions in Section 14. **Done**
2. Choose the default WhatsApp provider. **Done** (Provider A)
3. Get the dedicated WhatsApp number, recipient numbers and send times. **Waiting**
4. Start the legal review of face and plate recognition (reviewer, DPIA, lawful basis, signage, limits, client sign-off). **Waiting**
5. Hardware inventory per NVR. **In progress**: model is DS-7632NXI-K2/16P; firmware and tier mix come from the probe (task 12)
6. Quotes for GPU server, drives, UPS units and any fourth wall PC. **Waiting**
7. Wall PC details. **Answered**: 3 x Core i5, 16 GB, 55 inch Hisense TVs; Windows edition still to confirm
8. Open questions. **Answered**, except hosting provider and our code's license
9. Confirm the AI's assumptions. **Done**

**9a.** Resolve the NVR drive conflict (2 bays, Section 18). **Conflict**

**9b.** Accept per-camera qualification for broad recognition and its GPU budget (5.10). **Conflict**

**Stage B: Phase 0, Discovery and PoC**

10. Update the PoC plan to v0.5. **Done** (`docs/poc-plan-v0.5.md`)
11. Step 0: Docker Compose skeleton. **Done** in the build environment; repeat on the real server
12. Step 1: device capability probe. **Done** (built, 6 tests passing); run on all six NVRs: **Waiting**
13. Discovery across ColorVu, AcuSense, non-AI cameras and two firmware versions; test ISAPI pass-through to PoE cameras. **To do** (needs probe results)
14. Device compatibility matrix. Generator **Done**; confirming tiers **To do**
15. One non-AI camera end to end through a Tier S worker. **Done** on a sample video (0.16 to 0.26 s); run on a site camera: **Waiting**
16. GPU benchmark on NVIDIA with Intel comparison, with and without recognition. **To do**
17. Our worker versus Frigate. **To do**
18. Face and plate trial: entrance camera, then sample general cameras. **To do**
19. Wall PC capacity on an i5 PC and 55 inch TV (32 and 64 tiles, three TVs on one PC). Test page **Done**; site runs A to C: **Waiting**
20. NVR connection and bandwidth limits. **To do**
21. One-week WhatsApp gateway test with email fallback. **To do** (needs task 3)
22. Wall Agent and Windows installer prototype, 24-hour soak. Agent and installer **Done** (tested on Linux); Windows soak: **Waiting**
23. License scan of PoC code, models and datasets. **To do**
24. PoC go or no-go and requirements sign-off. **To do**

**Stage C: Phase 1, Foundation:** repository remote and CI; tenant-ready
schema with row-level security and branding fields; auth and admin;
device adapter (ISAPI, ONVIF, RTSP) with credentials vault and NVR
pass-through; network segments; Device Service health polling; tier
assignment with override; API gateway. Gate: add an NVR and see its
channels and tiers.

**Stage D: Phase 2, Live viewing:** stream gateway (pull once,
sub-streams, auto-reconnect); 32-channel NVR screens; rotation screen;
multi-monitor kiosk; Wall Agent; Windows wall installer; Linux wall
package; layout manager; Hisense TV and Windows hardening guide. Gate:
real wall PCs at 6 NVRs.

**Stage E: Phase 3, Edge events and alerts:** alertStream ingestion and
normalization; device analytics; rules and schedules; alert feed;
snapshots and clips; incident workflow; escalation; evidence vault;
offline queueing. Gate: real events raise alerts.

**Stage F: Phase 4, Server AI:** Tier S workers; image-quality checks;
supplement light scheduling; coverage dashboard; GPU benchmark; pinned
NVIDIA versions and staging. Gate: detection on a non-AI camera.

**Stage G: Phase 5, Geo features:** geotags; self-hosted maps and floor
plans; site map; geofence editor and push to devices; Traccar with
PostGIS; Android guard tracking; GPS events. Gate: breach walk-through.

**Stage H: Phase 6, Reporting and delivery:** DOCX and PDF reports;
uploadable branding, selectable language and timezone; scheduling and
archive; WhatsApp Provider A with email and ntfy fallback; delivery
tracking; recipients and subscriptions; reports center. Gate: client
reviews samples.

**Stage I: Phase 7, Face and plate:** watchlists; edge recognition
events; server engine; per-camera qualification; match review;
accuracy measurement. Gate: accuracy and legal sign-off.

**Stage J: Phase 8, Hardening and licensing:** RBAC, 2FA, audit,
privacy masking; TLS and VLAN guidance; backups and restore tests;
retention audit and drive alerts; per-site perpetual license service;
tenant isolation tests; performance and security tests; SBOM and
license scan; UPS. Gate: security checklist and 20-NVR load test.

**Stage K: Phase 9, Bundling and deployment:** Linux installer, VM
image and Compose package; Windows server backup installer (WSL2);
Windows wall installer; documentation and training; onboarding wizard;
hosted option with site connectors; pilot go-live. Gate: client
acceptance.

**Stage L: Phase 10, Growth (release 2.0):** remaining Section 5.8
items. Gate: prioritization session.
