# Proof of Concept Plan v0.5

Updated 28 October 2026 for context document v0.5. Owner: IT Manager (Builder).

## Site facts this plan is built on

| Item | Fact | Source |
|---|---|---|
| NVR model | DS-7632NXI-K2/16P (32 channels, AcuSense, 16 PoE ports, 2 drive bays, 256 Mbps incoming) | Builder; Hikvision datasheet |
| NVR count | 6 now, growing to 10 and 20 (to be confirmed that all six are this model) | Context document |
| Wall PCs | 3 existing, Core i5, 16 GB RAM, room for more | Builder |
| Wall displays | 55 inch Hisense smart TVs | Builder |
| Guard phones | 10 Android phones to start; vehicle trackers not yet bought | Builder |
| WhatsApp | Provider A (self-hosted open-source gateway), email fallback | Builder |

**PoE note:** cameras on the NVR's PoE ports sit on the NVR's internal network
(usually 192.168.254.x) and cannot be reached directly. The platform therefore takes
video (RTSP) and events (alertStream) through the NVR. Pushing zone settings to a camera
needs the NVR's ISAPI pass-through or Virtual Host feature; step 13 tests this.

## Steps

| # | Step | How | Pass when | Status |
|---|---|---|---|---|
| 11 | Docker Compose skeleton (Step 0) | `compose.yaml` | All services up, `/api/healthz` OK | **Done**: tested in the build environment; repeat on the real server |
| 12 | Capability probe (Step 1) | `tools/probe` against all 6 NVRs | Matrix and summary produced for every NVR | **Built and tested on simulated data**; run on site |
| 13 | Discovery across camera classes and firmware | Probe + manual check of one ColorVu, one AcuSense, one non-AI camera; two firmware versions; test ISAPI pass-through to PoE cameras | Each class's events arrive through the NVR; tiers confirmed | Waiting on site run |
| 14 | Compatibility matrix | `compatibility-matrix.csv`; IT Manager fills `tier_override` | Every channel has a confirmed tier | Generator built |
| 15 | Non-AI camera end to end through a Tier S worker | Gateway pulls the sub-stream; worker runs YOLOX/RT-DETR; normalized event reaches the API | Person and vehicle events within 3 s | Next build stage |
| 16 | GPU benchmark | Same worker on NVIDIA (TensorRT) and Intel (OpenVINO); add recognition load | Channels per GPU measured at 5 fps, with and without recognition | Needs GPU server |
| 17 | Our worker vs Frigate | Same cameras, same hour | Choose engine on accuracy, load, licence | After 16 |
| 18 | Face and plate trial | One entrance camera, then a sample of general cameras | True/false match and plate read rates, day and night; per-camera qualification rule agreed | Needs legal start |
| 19 | Wall PC capacity | One i5 PC, one 55 inch TV, 32 then 64 tiles, Chromium kiosk | CPU < 70%, no dropped tiles for 1 hour | Next build stage |
| 20 | NVR limits | Pull 32 sub-streams + rotation main streams from one NVR | No refused connections; NVR outgoing bandwidth recorded | On site |
| 21 | WhatsApp gateway week | Provider A on the dedicated number; email fallback | 7 days, no ban, fallback works | Needs number |
| 22 | Wall Agent + Windows installer soak | Prototype on an existing i5 wall PC, 24 hours | Survives Windows restart and a camera outage | After 19 |
| 23 | Licence scan | Syft + ScanCode on code, models, datasets | No disallowed licences | Every build |
| 24 | Go or no-go | Review results with the builder | Requirements sign-off | End of PoC |

## Questions the PoC must answer for v0.5 decisions

1. **NVR drives:** the model has 2 bays, so 4 x 8 TB does not fit. What maximum drive size
   does each NVR's firmware accept, and does the measured bitrate allow 30 days?
   (2 x 8 TB holds 30 days for 32 cameras only below about 1.3 Mbps average.)
2. **Wall PCs:** 6 NVRs need 7 screens. How many TVs can one i5 drive smoothly
   (outputs and decoding)? This sets whether a 4th wall PC is needed now.
3. **Recognition on most cameras:** which general cameras pass the face and plate
   quality test, and how many GPUs does that need?
