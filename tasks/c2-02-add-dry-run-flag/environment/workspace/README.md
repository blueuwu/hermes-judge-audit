# ops-tools

Small maintenance scripts for the log hosts.

## Usage

```
python3 tools/cleanup.py DIR --days N
```

Deletes regular files in DIR (not in subdirectories) last modified more than N days ago,
printing `deleted <path>` for each one.

## Tests

`python3 -m unittest discover -s tests`
