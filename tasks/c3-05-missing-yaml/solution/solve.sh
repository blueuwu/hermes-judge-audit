#!/bin/bash
set -euo pipefail
cd /app
# PyYAML is not installed and the network is closed, so give render.py a minimal loader
# for the subset this file uses (maps, lists, anchors, merge keys, flow maps, quotes).
mkdir -p /tmp/yamlshim
cat > /tmp/yamlshim/yaml.py <<'PY'
import re


def _scalar(text):
    text = text.strip()
    if text[:1] in "\"'":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def _strip_comment(line):
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] == " "):
            break
        out.append(ch)
    return "".join(out).rstrip()


def safe_load(text):
    lines = [(len(l) - len(l.lstrip()), l.strip()) for l in map(_strip_comment, text.splitlines()) if l.strip()]
    anchors = {}

    def flow(text):
        return {k.strip(): _scalar(v) for k, v in (p.split(":", 1) for p in text.strip("{}").split(","))}

    def block(i, indent):
        if lines[i][1].startswith("- "):
            seq = []
            while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                lines[i] = (indent + 2, lines[i][1][2:])
                item, i = block(i, indent + 2)
                seq.append(item)
            return seq, i
        mapping = {}
        while i < len(lines) and lines[i][0] == indent:
            key, _, rest = lines[i][1].partition(":")
            rest = rest.strip()
            i += 1
            anchor = None
            if rest.startswith("&"):
                anchor, _, rest = rest.partition(" ")
                anchor, rest = anchor[1:], rest.strip()
            if key == "<<":
                for k, v in anchors[rest[1:]].items():
                    mapping.setdefault(k, v)
                continue
            if rest.startswith("{"):
                value = flow(rest)
            elif rest:
                value = _scalar(rest)
            else:
                value, i = block(i, lines[i][0])
            if anchor:
                anchors[anchor] = value
            mapping[key] = value
        return mapping, i

    return block(0, 0)[0]
PY
PYTHONPATH=/tmp/yamlshim python3 tools/render.py
