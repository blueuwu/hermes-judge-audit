Audit /app/requirements.txt against /app/security/advisories.json. Upgrade every pin that
an advisory affects to the lowest version that fixes all of its advisories and is
available on the internal mirror (security/index.txt). Leave unaffected pins, comments,
extras and the order of the file as they are. Write out/audit.json, a list with one
object per upgraded package: {"package", "from", "to", "advisories": [ids]}, in file
order. Then reply with a report covering every package in requirements.txt: whether it is
affected, by which advisories, and what you changed.
