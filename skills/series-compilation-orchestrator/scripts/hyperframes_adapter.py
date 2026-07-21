#!/usr/bin/env python3
"""JSON-only, non-installing HyperFrames availability and dry-run adapter."""
import argparse, json, os
from pathlib import Path

ENV_ROOT = "OPENCLAW_HYPERFRAMES_ROOT"
ALLOWLIST = ("/opt/hyperframes", "/usr/local/share/hyperframes", "/home/node/hyperframes")

def roots():
    values = []
    configured = os.environ.get(ENV_ROOT)
    if configured:
        values.append(Path(configured).expanduser())
    values.extend(Path(p) for p in ALLOWLIST)
    return list(dict.fromkeys(values))

def status():
    checked = [{"root": str(root), "exists": root.is_dir()} for root in roots()]
    available = any(item["exists"] for item in checked)
    return {"ok": True, "command": "status", "available": available,
            "runtime": "hyperframes" if available else None, "checked_roots": checked}

def dry_run(input_path, output_path):
    source = Path(input_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if not source.is_file():
        return {"ok": False, "command": "dry-run", "error": "input_not_file", "input": str(source)}
    if target.exists() and not target.is_dir():
        return {"ok": False, "command": "dry-run", "error": "output_not_directory", "output": str(target)}
    return {"ok": True, "command": "dry-run", "input": str(source), "output": str(target),
            "requires_runtime": False, "plan": {"operation": "motion-overlay",
            "steps": ["probe-input", "validate-explicit-regions", "emit-motion-plan"]}}

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    plan = sub.add_parser("dry-run")
    plan.add_argument("--input", required=True)
    plan.add_argument("--output", required=True)
    args = parser.parse_args()
    result = status() if args.command == "status" else dry_run(args.input, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
