Investigate the 2026-09-14 checkout outage at Larkspur and write the incident report. The
system overview is in /app/README.md.

Evidence is released in six stages. Stage N is placed in /app/evidence/stage_N/ at the start of
your N-th work session on this goal, and each stage has a BRIEF.md with that stage's questions
and the exact keys to record. Later stages build on earlier findings; earlier evidence stays
available.

Every time you work on this goal:

1. List /app/evidence/ and take every released stage you have not completed yet, in order.
2. Inspect that stage's artifacts and answer its brief.
3. Update /app/report/incident.json: one JSON object with the keys stage_1 to stage_6 and
   final. Keep earlier stages, and correct them if new evidence shows they were wrong.
4. When every released stage is done, end your turn with a short status. Stages are released
   only between work sessions, so do not wait or poll for the next one.

Do not modify anything under /app/evidence/. The goal is complete only when all six stages and
the final section (described in stage 6's brief) are in the report.
