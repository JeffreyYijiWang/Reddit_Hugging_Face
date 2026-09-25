from __future__ import annotations

import collections
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .common import BudgetStop, check_disk, digest, dumps, load_json, now, permalink, save_json, typed_id
from .inspection import describe
from .keywords import Matcher, VERSION
from .store import Store
from .transport import Ledger, Relay

COLUMNS = ("id", "author", "subreddit", "created_utc", "title", "selftext", "body", "link_id", "parent_id", "score", "num_comments", "url", "permalink", "upvote_ratio", "over_18", "link_flair_text", "is_self", "edited", "removed_by_category", "crosspost_parent", "crosspost_parent_list")


def select_files(cfg, manifest, stage):
    scope = cfg["context" if stage == "context" else "discovery"]
    paths = scope.get("selected_paths") or []
    known = {f["path"] for f in manifest}
    if set(paths) - known:
        raise ValueError("Configured file absent from revision-pinned manifest")
    selected = [f for f in manifest if (not paths or f["path"] in paths)
            and f["kind"] in scope.get("kinds", ["submissions", "comments"])
            and (not scope.get("start_month") or f["month"] >= scope["start_month"])
            and (not scope.get("end_month") or f["month"] <= scope["end_month"])]
    # Posts first; newest available periods first. Every file remains in scope.
    return sorted(selected, key=lambda f: (f["kind"] != "submissions", -int(f["month"].replace("-", "")), f["path"]))


def canonical(row, file):
    result = dict(row)
    result["kind"] = file["kind"]
    result["typed_id"] = typed_id(row["id"], "t1" if file["kind"] == "comments" else "t3")
    result["thread_id"] = typed_id(row.get("link_id"), "t3") if file["kind"] == "comments" else result["typed_id"]
    if result["thread_id"] and not result["thread_id"].startswith("t3_"):
        raise ValueError("Comment link_id is not a submission ID")
    result["parent_id"] = typed_id(row.get("parent_id"), "t1") if row.get("parent_id") else None
    result["source"] = {k: file[k] for k in ("repo", "revision", "path", "url")}
    result["retrieved_at"] = now()
    result["archival_observation_time"] = None
    result["canonical_permalink"] = permalink(result)
    return result


def triage_flags(text):
    """Sampling strata only. These flags NEVER assign Yes/No annotations."""
    low = text.casefold()
    flags = []
    if any(x in low for x in ("if ", "might ", "would ", "hope ", "afraid", "worried", "in case", "don't want", "didn't", "did not")):
        flags.append("negation_or_hypothetical_language")
    if ">" in text or "\"" in text:
        flags.append("possible_quotation")
    if any(x in low for x in ("showed ", "told ", "gave ")):
        flags.append("possible_voluntary_sharing")
    return flags


def scan(cfg, stage="discovery", targets=None, files=None, resume=True, max_seconds=None, benchmark=False, continue_on_error=False):
    root = Path(cfg["data_root"])
    manifest = load_json(root / "inputs/source_manifest.json")["files"]
    files = files if files is not None else select_files(cfg, manifest, stage)
    queries = load_json(root / "inputs/keywords.json", [])
    query_hash = digest(queries)
    scope = cfg["context" if stage == "context" else "discovery"]
    target_hash = digest(sorted(targets or [])) if stage == "context" else None
    ledger = Ledger(cfg)
    ledger.check_time()
    store = Store(cfg)
    store.recover()
    relay = Relay(cfg, manifest, ledger)
    matcher = Matcher(queries)
    batch_size = cfg["resources"]["batch_size"]
    start = time.monotonic()
    last_accounted = start
    max_seconds = min(max_seconds or cfg["resources"]["max_query_seconds"], cfg["resources"]["max_query_seconds"] - ledger.data["query_seconds"])
    deadline = start + max_seconds
    relay.deadline = deadline
    run_id = stage + "_" + now().replace(":", "-")
    report = {"run_id": run_id, "stage": stage, "started": now(), "query_hash": query_hash, "matcher_version": VERSION,
              "target_hash": target_hash, "scope": scope, "selected_paths": [f["path"] for f in files], "files": [],
              "transfer_definition": "Measured upstream HTTP payload consumed; excludes transport overhead and OS read-ahead",
              "predicate_pushdown": "Month selection skips unselected files. SQL filters are pushed to Parquet reader; row-group skip counts unmeasured.",
              "subreddit_filter": cfg["discovery"].get("subreddits", []) if stage == "discovery" else []}
    before = ledger.data["payload_bytes"]
    negative_sample = load_json(root / "inspection/keyword_negative_sample.json", [])
    negative_ids = {r["typed_id"] for r in negative_sample}
    try:
        if queries:
            store.bulk("query_definitions", [dict(query_id=q["query_id"], json=dumps(q)) for q in queries])
        for file in files:
            if (root / 'state/stop_requested').exists():
                report['stop_reason'] = 'requested_stop'; break
            key = digest({"revision": file["revision"], "path": file["path"], "stage": stage, "scope": scope,
                          "query_hash": query_hash, "matcher_version": VERSION, "target_hash": target_hash})
            if resume and store.completed(key) and not benchmark:
                report["files"].append({"path": file["path"], "status": "previously_complete", "key": key})
                continue
            if time.monotonic() >= deadline:
                report["stop_reason"] = "time_budget"; break
            check_disk(cfg)
            reader = store.db.cursor()
            timer = threading.Timer(max(0.01, deadline - time.monotonic()), reader.interrupt)
            timer.daemon = True
            timer.start()
            detail = {"path": file["path"], "kind": file["kind"], "key": key, "stage": stage, "rows_returned": 0, "matched_records": 0,
                      "status": "partial",
                      "phrase_hits": 0, "matching_seconds": 0.0, "peak_rss_bytes": 0, "scope": scope, "target_hash": target_hash,
                      "target_ids": sorted(targets or []), "file_bytes": file["bytes"], "started": now()}
            file_start, byte_start = time.monotonic(), ledger.data["payload_bytes"]
            candidates, hits = [], []
            negative_count = 0
            try:
                url = relay.url(file)
                schema = file.get("schema") or describe(reader, url)
                columns = [c for c in COLUMNS if c in {x["name"] for x in schema}]
                if "id" not in columns:
                    raise ValueError("Missing id column")
                sql = "SELECT " + ",".join('"' + c + '"' for c in columns) + " FROM read_parquet(?)"
                params = [url]
                conditions = []
                if stage == "context":
                    if not targets:
                        raise ValueError("Context requires a nonempty target set")
                    if file["kind"] == "comments":
                        conditions.append("regexp_replace(link_id, '^t3_', '') IN (SELECT unnest(?))")
                    else:
                        conditions.append("regexp_replace(id, '^t3_', '') IN (SELECT unnest(?))")
                    params.append([x.removeprefix("t3_") for x in sorted(targets)])
                if stage == "discovery" and cfg["discovery"].get("subreddits"):
                    conditions.append("lower(subreddit) IN (SELECT unnest(?))")
                    params.append([s.lower() for s in cfg["discovery"]["subreddits"]])
                if conditions:
                    sql += " WHERE " + " AND ".join(conditions)
                detail["sql"] = sql
                detail["filter_parameters"] = params[1:]
                # Separate cursor keeps this reader alive while the sole writer persists batches.
                batches = reader.execute(sql, params).fetch_record_batch(batch_size)
                for batch in batches:
                    if (root / 'state/stop_requested').exists():
                        raise BudgetStop('requested_stop')
                    if time.monotonic() >= deadline:
                        raise BudgetStop("time_budget")
                    text_fields = ("title", "selftext") if file["kind"] == "submissions" else ("body",)
                    text_arrays = {field: batch.column(field).to_pylist() for field in text_fields if field in batch.schema.names}
                    def read_row(index):
                        return {name: batch.column(name)[index].as_py() for name in batch.schema.names}
                    for row_index in range(batch.num_rows):
                        detail["rows_returned"] += 1
                        if stage == "context":
                            candidates.append(canonical(read_row(row_index), file))
                            continue
                        match_start = time.perf_counter()
                        found = []
                        for field in text_fields:
                            for hit in matcher.find(text_arrays[field][row_index] or ""):
                                hit["field"] = field
                                found.append(hit)
                        detail["matching_seconds"] += time.perf_counter() - match_start
                        if found:
                            row = read_row(row_index)
                            r = canonical(row, file)
                            r["triage_flags"] = triage_flags("\n".join(row.get(f) or "" for f in ("title", "selftext", "body")))
                            candidates.append(r)
                            detail["matched_records"] += 1
                            detail["phrase_hits"] += len(found)
                            for h in found:
                                h.update({"typed_id": r["typed_id"], "thread_id": r["thread_id"], "query_set_hash": query_hash, "source": r["source"], "run_id": run_id})
                                h["hit_id"] = digest([r["typed_id"], h["query_id"], h["field"], h["start"], h["end"], file["revision"]])
                                hits.append(h)
                        elif negative_count < 2:
                            row = read_row(row_index)
                            r = canonical(row, file)
                            if r["typed_id"] not in negative_ids:
                                r["sampling_basis"] = "first two nonmatching records per selected shard; convenience check, not prevalence/recall sample"
                                negative_sample.append(r); negative_ids.add(r["typed_id"])
                            negative_count += 1
                    store.put_records(candidates)
                    store.put_hits(hits)
                    candidates, hits = [], []
                    detail["peak_rss_bytes"] = max(detail["peak_rss_bytes"], psutil.Process().memory_info().rss)
                    detail["payload_bytes"] = ledger.data["payload_bytes"] - byte_start
                    detail["elapsed_seconds"] = time.monotonic() - file_start
                    store.checkpoint(key, stage, file["path"], "partial", detail["rows_returned"], detail)
                    if detail["rows_returned"] % (batch_size * 32) == 0:
                        check_disk(cfg)
                detail["status"] = "complete"
            except Exception as exc:
                detail["status"] = "partial" if detail["rows_returned"] else "failed"
                detail["error"] = str(exc)
                report["stop_reason"] = "time_budget" if time.monotonic() >= deadline else type(exc).__name__
                if candidates:
                    try:
                        store.put_records(candidates); store.put_hits(hits)
                    except Exception as persistence_exc:
                        detail['persistence_failure'] = str(persistence_exc)
            finally:
                timer.cancel(); reader.close()
                detail["elapsed_seconds"] = time.monotonic()-file_start
                detail["payload_bytes"] = ledger.data["payload_bytes"]-byte_start
                detail["rows_per_second"] = detail["rows_returned"] / max(detail["elapsed_seconds"], 0.001)
                detail["restart_policy"] = "Restart incomplete shard without OFFSET; deduplicate by record and hit keys"
                store.checkpoint(key, stage, file["path"], detail["status"], detail["rows_returned"], detail)
                report["files"].append(detail)
                current_time = time.monotonic()
                ledger.data["query_seconds"] += current_time - last_accounted
                last_accounted = current_time
                ledger.flush()
                save_json(root / "state/live_progress.json", {"run_id": run_id, "stage": stage, "updated_at": now(), "active": True,
                    "selected_shards": len(files), "processed_shards": len(report["files"]),
                    "complete_shards": sum(f["status"] in ("complete", "previously_complete") for f in report["files"]),
                    "rows_this_run": sum(f.get("rows_returned", 0) for f in report["files"]),
                    "keyword_hits_this_run": sum(f.get("phrase_hits", 0) for f in report["files"]),
                    "payload_bytes_cumulative": ledger.data["payload_bytes"], "query_seconds_cumulative": ledger.data["query_seconds"],
                    "current_file": file["path"], "current_file_status": detail["status"]})
                save_json(root / "logs" / (run_id + ".json"), report)
                print(dumps({"stage": stage, "path": file["path"], "status": detail["status"], "rows": detail["rows_returned"], "hits": detail["phrase_hits"], "seconds": round(detail["elapsed_seconds"], 2)}), flush=True)
            if detail["status"] != "complete" and (detail.get('persistence_failure') or not continue_on_error or (root/'state/stop_requested').exists() or time.monotonic() >= deadline or ledger.data["payload_bytes"] >= cfg["resources"]["network_bytes"]-10000000):
                break
    finally:
        try:
            elapsed = time.monotonic()-start
            ledger.data["query_seconds"] += time.monotonic() - last_accounted
            ledger.flush()
            report["elapsed_seconds"] = elapsed
            report["payload_bytes"] = ledger.data["payload_bytes"]-before
            report["finished"] = now()
            from .common import disk_usage
            report["disk_bytes"] = disk_usage(root)
            report["complete"] = len(report["files"]) == len(files) and all(f["status"] in ("complete", "previously_complete") for f in report["files"])
            save_json(root / "logs" / (run_id + ".json"), report)
            save_json(root / "inspection/keyword_negative_sample.json", negative_sample)
            store.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?)", [run_id, dumps(report)])
            progress = load_json(root / "state/live_progress.json", {})
            progress.update(active=False, finished_at=now(), complete=report["complete"], stop_reason=report.get("stop_reason"))
            save_json(root / "state/live_progress.json", progress)
        finally:
            relay.close(); store.close()
    return report
