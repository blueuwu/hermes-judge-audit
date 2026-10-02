# events-export

`python3 bin/export_events.py --since YYYY-MM-DD` writes business events to
`out/events.csv`.

On a workstation, point it at the local snapshot with `EVENTS_DB=db/app.db`; without it,
the script reads the production replica path, which exists only on the reporting hosts.
