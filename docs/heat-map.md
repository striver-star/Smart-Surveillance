# Incident heat map

Release 2.0, second batch. **Incident heat map** in the console (administrators, CSO, operators, management)
shows where and when alerts happen, to plan patrols, lighting and cameras.

- **Where**: the site plan with a bubble at each placed camera, sized and shaded by its number of alerts,
  and zones shaded the same way. Hover for the counts (real, false, busiest hour); click a camera or zone
  to see its hours.
- **When**: alerts by day of the week and hour (site time, `HSS_TZ`), the busiest hour, the share between
  18:00 and 06:00, and a bar of all days by hour.
- **Places with the most alerts**: the top 15 cameras with alerts, critical, real incidents, false alarms and
  busiest hour. Cameras not placed on the plan still appear here.
- **Filters**: 7, 30, 90 days or a year; all alerts, without false alarms, or only alerts closed as real
  incidents; any severity or critical only; the site plan when there are several.

Device alerts (camera or NVR offline, drive faults) are left out; missed patrols and guard SOS are counted
at their checkpoint.

**Reading it**: with "Real incidents" the map shows where real trouble happens, which is what patrol routes
and lighting should follow. With "All alerts" it also shows noise; compare it with the False alarms page.
For the picture to be right, place every camera on the site plan (Site map › Cameras) and close alerts with
the right reason.

API: `GET /api/insights/heatmap?days=30&only=all|not_false|real&severity=&place=camera:<id>|zone:<name>&plan_id=`.
