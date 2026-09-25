from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .cases import extract_links, group_seeds, preservation_candidates
from .common import digest, dumps, load_json, now, save_json
from .scanner import scan
from .store import Store


def post_bundles(cfg):
    """Post-first collection units; no remote context query or invented originals."""
    root = Path(cfg["data_root"])
    store = Store(cfg, remote=False)
    records, hits = store.records(), store.hits()
    by_id = {r["typed_id"]: r for r in records}
    by_thread, hits_by_record = {}, {}
    for hit in hits:
        hits_by_record.setdefault(hit['typed_id'], []).append(hit)
    for r in records:
        by_thread.setdefault(r["thread_id"], []).append(r)
    groups = group_seeds(records, hits)
    case_paths, edges = [], {}
    for gid, seeds in groups.items():
        thread = by_id[seeds[0]]["thread_id"]
        rows = by_thread.get(thread, [])
        original = by_id.get(thread)
        iid = "i_" + digest([cfg["dataset_revision"], gid])[:20]
        links = []
        for row in rows:
            for edge in extract_links(row, (original or {}).get("author")):
                links.append(edge); edges[edge["link_id"]] = edge
        unresolved = sorted({e["target_thread"] for e in links if e["supported"] and e["target_thread"] not in by_id})
        fullpost = original and original["kind"] == "submissions"
        coverage = {"mode": "post-first; comment reconstruction optional per user", "comments_collected": False,
            "retrieved_comments": sum(r["kind"] == "comments" for r in rows), "comment_count_interpretation": "Retained matching comments or prior pilot context; not all comments",
            "complete_case": False, "all_available_comments_in_declared_scope": False,
            "missing_submission_ids": [] if fullpost else [thread], "unresolved_related_ids": unresolved,
            "context_not_requested": True, "selected_for_reconstruction": False,
            "current_accessibility_checked": False, "author_history_collected": False}
        bundle = {"incident_id": iid, "provisional_grouping_key": gid, "seed_record_ids": seeds, "seed_thread_id": thread,
            "original_post_id": thread if fullpost else None, "original_resolution_status": "provisional seed thread" if fullpost else "unresolved",
            "members": [{"post_id": thread, "created_utc": original.get("created_utc"), "relative_to_discovery": "unknown"}] if fullpost else [],
            "records": rows, "record_ids": sorted(r["typed_id"] for r in rows),
            "comments_by_thread": {thread: [r["typed_id"] for r in rows if r["kind"] == "comments"]},
            "series_links": links, "preservation_candidates": preservation_candidates(rows), "coverage": coverage,
            "keyword_hits": [h for seed in seeds for h in hits_by_record.get(seed, [])], "assembled_at": now()}
        bundle["content_hash"] = digest({"records": [{k:v for k,v in r.items() if k != "retrieved_at"} for r in rows], "coverage": coverage, "seeds": seeds})
        path = root / "cases" / (iid + ".json")
        save_json(path, bundle); case_paths.append(str(path))
    store.bulk("links", [{"link_id": k, "json": dumps(v)} for k,v in edges.items()])
    store.close()
    save_json(root / "cases/index.json", {"case_paths": case_paths, "mode": "post-first", "grouping_note": "Provisional collection units, not confirmed distinct incidents"})
    return {"case_units": len(groups), "comment_reconstruction": "optional; not run"}


def finalize(cfg, workbook=True):
    from .annotate import annotate
    from .export import export
    from .report import report
    bundles = post_bundles(cfg)
    annotations = annotate(cfg, resume=True)
    result = export(cfg, workbook=workbook)
    report(cfg)
    return {"bundles": bundles, "annotations": annotations, "exports": result}


def run_full(cfg):
    root = Path(cfg["data_root"])
    status_path = root / "state/full_run_status.json"
    status = {"pid": os.getpid(), "started_at": now(), "state": "running", "query_limit_seconds": cfg["resources"]["max_query_seconds"],
        "scope": "All available repository files, submissions first then comments. Complete processing must be verified from manifest checkpoints.",
        "comment_reconstruction": "not requested", "config_path": cfg["config_path"],
        "checkpoint_resume": True}
    save_json(status_path, status)
    try:
        if cfg['resources'].get('workers',1) > 1:
            from .parallel import scan_parallel
            run = scan_parallel(cfg)
        else:
            run = scan(cfg, resume=True, max_seconds=cfg["resources"]["max_query_seconds"], continue_on_error=True)
        status["discovery_complete"] = run["complete"]
        status["stop_reason"] = run.get("stop_reason", "selected_files_exhausted")
        status["state"] = "exporting"
        save_json(status_path, status)
        status["results"] = finalize(cfg)
        status["state"] = "complete" if run["complete"] else "stopped_with_partial_coverage"
    except BaseException as exc:
        status.update(state="failed_or_interrupted", error=type(exc).__name__ + ": " + str(exc))
        try:
            status["results"] = finalize(cfg)
        except Exception as export_exc:
            status["export_error"] = str(export_exc)
        raise
    finally:
        status["finished_at"] = now()
        save_json(status_path, status)
    return status
