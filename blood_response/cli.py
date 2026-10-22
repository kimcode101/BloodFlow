import argparse
import hashlib
import json
from pathlib import Path
import time
from .model import ROOT, DEFAULT_DATA, load_world, validate, plan, advance

def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic blood-response demo: one shared data contract")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="Offline data and provenance checks")
    p = commands.add_parser("plan", help="Next-day forecast and transfer proposals, no database writes")
    p.add_argument("--traffic", choices=["normal", "rush"], default="rush")
    p.add_argument("--output", type=Path)
    s = commands.add_parser("simulate", help="Offline by default; --database opts into PostgreSQL writes")
    s.add_argument("--ticks", type=int, default=24, help="One-hour ticks; zero runs until interrupted")
    s.add_argument("--interval", type=float, default=0)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--output", type=Path, default=ROOT / "runs" / "blood-simulation")
    s.add_argument("--database", action="store_true")
    s.add_argument("--schema", default="blood_demo")
    d = commands.add_parser("load", help="Load canonical data into a dedicated demo schema")
    d.add_argument("--schema", default="blood_demo")
    d.add_argument("--reset", action="store_true", help="Replace this module's objects in the chosen demo schema")
    d.add_argument("--validate-only", action="store_true")
    social = commands.add_parser("normalize-social", help="Apply shared policy to recorded responses; no API calls")
    social.add_argument("--reports", type=Path, required=True)
    social.add_argument("--predictions", type=Path, required=True)
    social.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "normalize-social":
        from .social import normalize
        reports = [json.loads(s) for s in args.reports.read_text(encoding="utf-8").splitlines() if s.strip()]
        result = normalize(reports, json.loads(args.predictions.read_text(encoding="utf-8")))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"reports": len(result), "live_api_calls": 0, "output": str(args.output)}))
        return
    world = load_world(args.data)
    result = validate(world)
    if args.command == "validate" or (args.command == "load" and args.validate_only):
        manifest = ROOT / "data" / "integration_report.json"
        if manifest.exists():
            for source in json.loads(manifest.read_text(encoding="utf-8"))["sources"]:
                if hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() != source["sha256"]:
                    raise ValueError("Raw source hash mismatch: " + source["path"])
            result["raw_source_hashes"] = "PASS"
        print(json.dumps(result, indent=2))
    elif args.command == "plan":
        result = plan(world, args.traffic)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    elif args.command == "load":
        from .database import load_database
        print(json.dumps(load_database(world, args.schema, args.reset), indent=2))
    else:
        if args.ticks < 0 or args.interval < 0:
            parser.error("ticks and interval must be nonnegative")
        if args.database:
            from .database import database_tick
        else:
            args.output.mkdir(parents=True, exist_ok=False)
        tick = 0
        while args.ticks == 0 or tick < args.ticks:
            result = database_tick(args.schema, advance, args.seed) if args.database else advance(world, seed=args.seed)
            tick += 1
            if not args.database:
                validate(world)
                with (args.output / "ticks.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(result) + "\n")
                (args.output / "state.json").write_text(json.dumps(world, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result), flush=True)
            if args.interval and (args.ticks == 0 or tick < args.ticks):
                time.sleep(args.interval)
