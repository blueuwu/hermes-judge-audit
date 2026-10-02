"""Render config/services.yaml into out/services.json for the deploy tooling.

Each service is merged over the defaults; env is merged key by key, so a service's env adds
to the default env rather than replacing it. Disabled services are left out.
"""

import json
from pathlib import Path

import yaml


def render(doc: dict) -> dict:
    defaults = doc["defaults"]
    out = []
    for svc in doc["services"]:
        if not svc.get("enabled", True):
            continue
        env = {**defaults["env"], **svc.get("env", {})}
        out.append(
            {
                "name": svc["name"],
                "url": f"http://{svc['host']}:{svc['port']}{svc['health_path']}",
                "replicas": svc["replicas"],
                "env": dict(sorted(env.items())),
            }
        )
    return {"services": sorted(out, key=lambda s: s["name"])}


if __name__ == "__main__":
    doc = yaml.safe_load(Path("config/services.yaml").read_text())
    Path("out").mkdir(exist_ok=True)
    Path("out/services.json").write_text(json.dumps(render(doc), indent=2) + "\n")
    print("rendered out/services.json")
