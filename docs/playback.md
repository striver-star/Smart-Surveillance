# Playback of recordings

**Playback** (administrators, CSO, operators) plays any camera's recording from its NVR, for cameras on
NVRs added in Devices. Recordings stay on the NVRs; nothing is copied to the server.

## Use

- Pick the camera and day. The timeline shows the hours the NVR recorded (blue) and the events HSS
  received (marks: blue info, amber warning, red critical). **24 h / 6 h / 1 h** zooms around the
  playhead.
- **Click the timeline** to play from that moment, or set a time and **Play from this time**.
- **−10 min … +10 min** jump; **Stop** ends playback. Click an event in the list to play from 10 seconds
  before it.
- From an alert: **Play recording** opens Playback 10 seconds before the alert.

Every playback is in the audit log (who, which camera, from when).

## How it works

The API asks the stream gateway for a temporary stream with a random name, fed by the NVR's RTSP
playback address from the chosen time (`/Streaming/tracks/<channel>01?starttime=…`, the NVR's local
time). The console plays it over WebRTC like live view. A jump starts a new stream; a stream nobody is
watching is removed after 3 minutes.

## Limits

- Playback runs at normal speed; jump to move faster.
- Recordings are the main stream. A camera recording in **H.265** plays on iPhone and in Chrome or Edge
  on PCs with hardware H.265 support; on other PCs the picture stays black ("No video"). Setting the
  camera's main stream to H.264 avoids it, at about 30 to 40% more storage.
- The NVR user needs **Remote Playback** (already in the HSS user's rights, docs/edge.md).
- Times are shown in the PC's time zone: set wall and control-room PCs to Africa/Lagos.
