# Smart search

Release 2.0, third batch. **Smart search** in the console (administrators, CSO, operators, viewers) finds people
and vehicles by colour in the pictures of stored events: "a person in a red top and blue trousers at the gate
cameras last night", "a white vehicle this week".

## How it works

- The **attribute service** (`attributes`, starts with `docker compose --profile ai up -d`) looks at the snapshot of
  every event with a picture: Hikvision AcuSense and DeepinView events, the server AI and the edge service. It finds
  the people and vehicles (the same YOLOX model as the server AI) and reads their colours: a person's top and
  bottom, a vehicle's body. New events are done within seconds; older ones (back to 90 days) in the background.
  On the sandbox's CPU it took about 30 seconds for 190 pictures.
- **Search** by person, vehicle or anything; any of up to 11 colours for each part; camera; time (up to 31 days at a
  time). Results are tiles of the person or vehicle cut out of the picture, newest first, with **Play** (Playback
  10 seconds before) and **Alert**.
- The same object at the same spot in many pictures (a parked car, a sign) shows once, marked "in N pictures:
  parked?", instead of a page of copies.

## Limits to know

- Only moments that raised an event with a picture can be found: it searches event pictures, not all recorded video.
  Cameras with line crossing or intrusion events (and the server AI) give the best coverage.
- Colours are read from small pictures: dark navy reads as black, and at night under infrared everything reads as
  grey or black. Pick two or three neighbouring colours when unsure.
- Searching the NVRs' own attribute search (on AcuSense and DeepinView recorders) isn't used: its calls differ by
  model and firmware; it can be added after testing on the site's recorders.

## Privacy

Nobody is identified: clothing and vehicle colours only. Face and plate recognition pictures are never analysed or
shown. Results follow each user's camera list (docs/camera-access.md). Every search (what was searched, not the
results) is in the audit log; playing a result is in the viewing log. Attributes are deleted with their event.
