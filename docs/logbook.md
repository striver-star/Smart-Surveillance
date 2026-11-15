# Logbook and shift handover

**Logbook** (operators, CSO, administrators write; management reads).

- **Shifts:** set under Settings › Shifts (default Day 06:00-18:00, Night 18:00-06:00, local time). The
  Logbook opens on the current shift; **Earlier shift / Later shift** step through past ones.
- **Entries:** patrol, incident, visitor, maintenance or other, with the writer's name and time. The log
  is append-only: the author can correct an entry for 15 minutes (it shows "corrected"); after that,
  corrections are new entries. An entry can be linked to an alert; it then also appears in the alert's
  timeline.
- **Handover:** **Hand over shift** records the outgoing operator's notes ("things to watch") and a summary
  HSS writes: alerts raised by severity, alerts still open (with who has them), device problems in the
  shift, sirens or lights still on, and the entries. The next operator sees "Handover waiting" on the
  Overview and in the Logbook, reads it and presses **Take over** (with an optional note). The person
  handing over can't take over their own handover, and only one person can take it.
- Handovers and shift changes are in the audit log.

Times are shown in the PC's time zone: set control-room PCs to Africa/Lagos.
