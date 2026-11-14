# Watchlist folder (example)

Copy to `config/watchlist/` (git ignores it) and replace the examples.

- `faces/<person_id>/person.json`: name, list (`blocked`, `vip`, `staff`, ...) and `consent_ref`,
  the reference to the signed consent form or the legal authority for enrolling this person.
  A person without `consent_ref` is not enrolled.
- `faces/<person_id>/*.jpg`: 2 to 5 clear, front-facing photos with one face each, eyes at least
  about 60 pixels apart. Photos that fail the quality check are listed in the trial report.
- `plates.csv`: `plate,list,note`, list is `allow` or `block`. Spaces and dashes in plates are ignored.

Keep this folder on the server only. It holds personal data.
