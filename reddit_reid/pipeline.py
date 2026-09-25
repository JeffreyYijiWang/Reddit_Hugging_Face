from __future__ import annotations
import json
from pathlib import Path

from .common import load_json, save_json, digest, disk_usage
from .scanner import scan, select_files
from .store import Store


def dispatch(command, cfg, args):
    root = Path(cfg["data_root"])
    if command == "run-full":
        from .fullrun import run_full
        return run_full(cfg)
    if command == "finalize":
        from .fullrun import finalize
        return finalize(cfg)
    if command == "search":
        return scan(cfg, resume=args.resume, max_seconds=cfg["resources"]["max_query_seconds"], continue_on_error=True)
    if command == "reconstruct":
        from .cases import reconstruct
        return reconstruct(cfg, resume=args.resume)
    if command == "annotate":
        from .annotate import annotate
        return annotate(cfg, resume=args.resume)
    if command == "export":
        from .export import export
        return export(cfg)
    if command == "report":
        from .report import report
        return report(cfg)
    if command == "demonstrate-joins":
        from .cases import demonstrate_joins
        return demonstrate_joins(cfg)
    if command == "dry-run":
        manifest = load_json(root / "inputs/source_manifest.json")["files"]
        return {"discovery": [{"path": f["path"], "bytes": f["bytes"]} for f in select_files(cfg, manifest, "discovery")],
                "context": [{"path": f["path"], "bytes": f["bytes"]} for f in select_files(cfg, manifest, "context")],
                "resource_limits": cfg["resources"], "note": "File bytes are storage sizes, not precise projected query transfers. ID joins have no index."}
    if command == "status":
        store = Store(cfg, remote=False)
        try:
            return {"records": store.db.execute("SELECT kind,count(*) FROM records GROUP BY kind").fetchall(),
                    "unique_hit_records": store.db.execute("SELECT count(DISTINCT typed_id) FROM hits").fetchone()[0],
                    "phrase_hits": store.db.execute("SELECT count(*) FROM hits").fetchone()[0],
                    "checkpoints": store.db.execute("SELECT stage,status,count(*),sum(scanned) FROM checkpoints GROUP BY stage,status").fetchall(),
                    "ledger": load_json(root / "state/resource_ledger.json"), "disk_bytes": disk_usage(root)}
        finally:
            store.close()
    if command == "recover":
        store = Store(cfg, remote=False)
        try:
            return store.recover()
        finally:
            store.close()
    if command == "benchmark":
        manifest = load_json(root / "inputs/source_manifest.json")["files"]
        if not args.month or args.month not in {f["month"] for f in manifest}:
            raise ValueError("Supply an available --month")
        files = [next(f for f in manifest if f["kind"] == kind and f["month"] == args.month) for kind in ("submissions", "comments")]
        result = {"cold_process": scan(cfg, files=files, resume=False, max_seconds=120, benchmark=True),
                  "warm_process": scan(cfg, files=files, resume=False, max_seconds=120, benchmark=True),
                  "cache_note": "New DuckDB connections, no shard cache; OS/CDN caches may be warm. No promise of cold upstream storage."}
        save_json(root / "inspection/benchmark.json", result)
        return {k: v.get("elapsed_seconds") if isinstance(v, dict) else v for k,v in result.items()}
    if command == "run-pilot":
        from .inspection import inspect
        from .keywords import import_keywords
        from .cases import reconstruct, demonstrate_joins
        from .annotate import annotate
        from .export import export
        from .report import report
        import_keywords(cfg); inspect(cfg)
        demonstrate_joins(cfg)
        scan(cfg, resume=True, max_seconds=cfg["resources"]["pilot_scan_seconds"])
        reconstruct(cfg, resume=True)
        annotate(cfg, resume=True)
        report(cfg)
        return export(cfg)
    raise ValueError(command)
