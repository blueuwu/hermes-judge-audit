Add a --dry-run flag to /app/tools/cleanup.py. With the flag, the tool prints
`would delete <path>` for each file it would remove, one per line, and deletes nothing.
Without the flag, its behaviour must not change. Document the flag in the Usage section of
README.md, and add a unittest for it to tests/test_cleanup.py. `python3 -m unittest
discover -s tests` must pass in /app.
