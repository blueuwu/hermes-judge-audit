"""Serialise API payloads deterministically."""

import json


def dumps(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
