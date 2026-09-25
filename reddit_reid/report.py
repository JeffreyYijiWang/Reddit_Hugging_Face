from __future__ import annotations

import collections
import json
from pathlib import Path

from .common import digest, load_json, now, save_json
from .scanner import select_files
from .store import Store


def report(cfg):
    root = Path(cfg["data_root"])
    manifest = load_json(root / "inputs/source_manifest.json")
    inventory = load_json(root / "inspection/inventory_summary.json", {})
    samples = load_json(root / "inspection/samples.json", [])
    audit = load_json(root / "inputs/keyword_audit.json", {})
    ledger = load_json(root / "state/resource_ledger.json", {})
    joins = load_json(root / "inspection/join_demonstration.json", {})
    store = Store(cfg, remote=False)
    checkpoints = [json.loads(j) | {"status": s, "scanned": n, "stage": stage} for j,s,n,stage in store.db.execute("SELECT json,status,scanned,stage FROM checkpoints").fetchall()]
    complete_by_file = {}
    for c in checkpoints:
        if c["stage"] == "discovery" and c["status"] == "complete" and not c.get("scope", {}).get("subreddits"):
            if c["path"] not in complete_by_file or c["scanned"] > complete_by_file[c["path"]]["scanned"]:
                complete_by_file[c["path"]] = c
    scope_files = select_files(cfg, manifest["files"], "discovery")
    completed = [f for f in scope_files if f["path"] in complete_by_file]
    native_paths = {c['path'] for c in checkpoints if c.get('prefilter')}
    negatives = load_json(root/'inspection/keyword_negative_sample.json', [])
    for row in negatives:
        if row.get('source', {}).get('path') in native_paths:
            row['sampling_basis'] = 'First two exact nonmatches surviving the native necessary-word filter per shard; convenience sample only'
    save_json(root/'inspection/keyword_negative_sample.json', negatives)
    scan_rows = sum(complete_by_file[f["path"]]["scanned"] for f in completed)
    hit_count, candidate_records, threads = store.db.execute("SELECT count(*),count(DISTINCT typed_id),count(DISTINCT json_extract_string(json,'$.thread_id')) FROM hits").fetchone()
    labels = store.db.execute("SELECT json_extract_string(json,'$.confirmed_reidentification'),json_extract_string(json,'$.review_status'),count(*) FROM annotations GROUP BY 1,2").fetchall()
    store.close()
    text = ["# Research run report", "", f"Generated {now()}.", "", "## Scope and status", "",
        f"Source: [{manifest['repo']}](https://huggingface.co/datasets/{manifest['repo']}/tree/{manifest['revision']}). Immutable revision `{manifest['revision']}`.",
        f"Completed {len(completed):,} of {len(scope_files):,} selected discovery files; {scan_rows:,} records in those completed files. Partial-file rows are recorded separately in checkpoints.",
        f"{hit_count:,} distinct phrase-span hits, {candidate_records:,} unique matching records and {threads:,} unique containing threads.",
        "These are lexical candidates. They are not confirmed incidents or prevalence estimates. Provisional case grouping is not an adjudicated incident count.",
        "The user's latest instruction requires full-post and all-available-comment review. Discovery scans submissions and comment text; thread reconstruction is separately tracked. This archive's comment coverage ends in 2012-08, so modern threads remain missing comments.",
        f"Configured cumulative query ceiling: {cfg['resources']['max_query_seconds']/3600:.1f} hours. Query time consumed: {ledger.get('query_seconds',0):.1f} seconds. HTTP payload consumed: {ledger.get('payload_bytes',0):,} bytes.",
        "Payload measurement excludes headers, TLS/TCP overhead and OS/network read-ahead. No raw monthly archive is downloaded to disk. DuckDB reads selected Parquet ranges through an allowlisted local relay.",
        "", "## Repository inventory", "", "| Type | Files | Compressed bytes | First available month | Last available month |", "|---|---:|---:|---|---|"]
    for kind in ("submissions", "comments"):
        i = inventory.get(kind, {})
        text.append(f"| {kind} | {i.get('shards')} | {i.get('bytes')} | {i.get('first_month')} | {i.get('last_month')} |")
    text += ["", "Actual file layout is `data/{comments|submissions}/YYYY/MM/NNN.parquet`. The card declares configurations comments/submissions, each with train split. Inventory covers this repository, not open-index/arctic.",
        "Comments end at 2012-08. Submission months are discontinuous, including a gap at 2011-06 and extensive gaps after 2013. A file's presence does not prove its month is complete.",
        "The full month list and asymmetric availability are in `inspection/inventory_summary.json`; every file and byte size is in `inputs/source_manifest.json`. Row counts/schema are verified only for inspected or scanned files; untouched entries remain null.",
        "", "## Executed text inspection", "", "The samples are actual range-read rows, not dataset-card JSON. Sampling selects the first physical five rows from the first shard of early, middle and recent available months, separately for each type. It is deterministic at the pinned revision and is not representative sampling.", ""]
    for sample in samples:
        if sample.get("error"):
            text.append(f"- {sample['path']}: failed: {sample['error']}")
            continue
        text.append(f"- {sample['kind']} {sample['period']} ({sample['month']}): {sample['shard_row_count']:,} rows in sampled shard; five-row text statistics `{json.dumps(sample['text_statistics_sample_only'])}`; sample subreddit frequencies `{json.dumps(sample['subreddit_frequencies_sample_only'])}`.")
    text += ["", "Restricted sample rows, IDs, full text, schemas and executed SQL are in `inspection/samples.json`. Public report omits usernames and case details. Both types have subreddit and created_utc. Submissions carry title/selftext; comments carry body/link_id/parent_id. Removed/deleted placeholders coexist with real text; empty selftext is not a reliable is_self indicator.",
        "", "## Actual ID join demonstration", "", f"Result: `{json.dumps(joins, ensure_ascii=True)}`", "",
        "This experiment batches submission IDs and comment link IDs across the December 2005 files. It demonstrates retrieval capability, not efficient indexing, current web accessibility or re-identification. Any failed join remains listed.",
        "", "## Keyword audit", "", f"Workbook: `{audit.get('filename')}`; SHA-256 `{audit.get('sha256')}`.",
        f"Imported {audit.get('original_count'):,} phrase occurrences, {audit.get('unique_count'):,} unique normalized queries, {audit.get('duplicate_count'):,} duplicate occurrences. Added zero expansions.",
        f"Aggregate-only phrases: {len(audit.get('only_aggregate',[]))}; category-only phrases: {len(audit.get('only_category',[]))}. Every originating sheet, row, category, target term and template remains in `inputs/keywords.json`.",
        "The local filename lacks the prompt's (4) suffix. The user explicitly identified this local workbook. Its contents/hash are recorded without claiming it is byte-identical to another version.",
        "Matching applies Unicode NFKC, case folding, whitespace/apostrophe normalization and enumerated recognise/realise spelling equivalences. Raw offsets are reconstructed and validated. Title/body are scanned separately. All queries execute together through Aho-Corasick, not one corpus scan per phrase.",
        "The parallel reader uses a conservative native required-word filter with a Unicode compatibility escape hatch, followed by exact matching. Complete native scans count all shard records from verified Parquet metadata; partial counts are lower bounds on returned potential matches. Convenience negatives surviving this filter cannot estimate corpus recall or precision.",
        "Large spreadsheets are partitioned across numbered workbooks, with complete CSV/JSONL exports and workbook_manifest.json recording all table row ranges. No candidate is omitted merely to fit one workbook.",
        "", "## Annotation, review and missing fields", "", f"Label/status counts: `{json.dumps(labels)}`.",
        "The Codex CLI uses the user's ChatGPT login for model review when its qualification checks pass. Schema, exact source spans, complete supplied record IDs and case hashes are validated locally. Model labels remain model-generated and require human adjudication; schema validity does not establish factual truth. Four purposive assistant reference cases are a qualification check, not a random accuracy benchmark. Unreviewed candidates remain pending; reviewed Unsure is counted separately. The failed local Qwen trial is excluded. Reviewer label/notes columns remain editable.",
        "The full annotation schema includes original properties, evidence spans/roles, reporter/finder distinctions, relationship subtypes and graph distance, discovery chain, account specifics, preservation and every requested outcome. Synthetic completeness fixtures are labeled and kept outside research cases.",
        "Historical account age, lifetime pre-post activity totals, contemporaneous visitors/contributors/traffic, exact up/down votes, upvote_ratio and is_self are unavailable in the inspected schemas. They remain null. Score and num_comments are archive snapshots. Current account/post status is unverified. Observed selected-record history proxies are separately named and never substituted.",
        "Keyword-negative convenience examples are retained for review but do not support a recall estimate. No independently adjudicated labels or known-case set were supplied, so precision, agreement/confusion matrices and population recall remain unavailable.",
        "", "## Cost, limits and resumption", ""]
    successful = [c for c in complete_by_file.values() if c.get("elapsed_seconds", 0) > 0]
    per_kind = {}
    for kind in ("submissions", "comments"):
        subset = [c for c in successful if c.get("kind") == kind]
        if subset:
            rows = sum(c["scanned"] for c in subset)
            sec = sum(c["elapsed_seconds"] for c in subset)
            rate = rows/sec
            source_bytes = sum(c.get("file_bytes",0) for c in subset)
            total_bytes = sum(f["bytes"] for f in manifest["files"] if f["kind"] == kind)
            estimate = sec*total_bytes/max(source_bytes,1)
            per_kind[kind] = {"measured_records": rows, "seconds": sec, "rows_per_second": rate, "file_bytes_sampled": source_bytes,
                              "estimated_full_seconds_low": estimate*.5, "estimated_full_seconds_high": estimate*2,
                              "assumption": "Scale summed file durations by compressed bytes. Worker effort, not parallel wall time. 0.5x-2x sensitivity, not a confidence interval"}
            text.append(f"- {kind}: {rows:,} measured rows in {sec:.1f} summed file-seconds ({rate:,.0f} rows per file-second). Full-type extrapolation {estimate*.5/3600:.1f}-{estimate*2/3600:.1f} worker-hours under 0.5x-2x variability. Overlapping readers mean this is not a wall-clock completion estimate. Text length/network/cache differences may invalidate it.")
    text += ["", "Cold/warm benchmark command records separate executions and does not imply clearing upstream CDN caches. Per-file logs include matcher time, process RSS samples, elapsed time and payload bytes. RSS is sampled, not a guaranteed system peak; DuckDB's memory limit does not include every Python allocation.",
        f"The full run has a 220 GB payload ceiling. {cfg['resources'].get('workers',1)} reader processes share one database writer through durable handoff files, with {cfg['resources'].get('worker_memory_limit','512MB')} DuckDB memory and one thread per reader. Workers are recycled to limit retained allocations. Query time is coordinated elapsed wall time, not summed worker times. Durable research data has a 5 GB ceiling. The persistent seven-hour query limit is not reset on restart; partial coverage is exported at resource limits. Failed files remain recorded.",
        "An unfinished shard is restarted and deduplicated; no remote OFFSET pagination is used. Keys include revision, file, stage, scope, query hash, matcher version and context target-set hash. Durable canonical records precede checkpoint commits. `recover` recatalogs orphan Parquet chunks. Annotation and export use local records only.",
        "Do not run a second DuckDB writer while a scan is active. `state/live_progress.json`, `state/full_run_status.json` and console logs are readable without opening the database.",
        "", "## Sources", "", "- [Hugging Face repository](https://huggingface.co/datasets/Dk587/arctic)",
        "- [DuckDB HTTP range access](https://duckdb.org/docs/current/core_extensions/httpfs/https)",
        "- [DuckDB Hugging Face revisions](https://duckdb.org/docs/current/core_extensions/httpfs/hugging_face)",
        "- [Kang, Brown and Kiesler, CHI 2013](https://www.cs.cmu.edu/~kiesler/publications/2013/2013_why-people-seek-anonymity.pdf)", ""]
    (root / "exports/research_report.md").write_text("\n".join(text), encoding="utf-8")
    save_json(root / "inspection/cost_estimate.json", per_kind)
    save_json(root / "exports/coverage_summary.json", {"selected_files": len(scope_files), "complete_files": len(completed), "records_in_complete_files": scan_rows,
            "matching_records": candidate_records, "keyword_hits": hit_count, "unique_threads": threads, "labels": labels, "all_selected_files_complete": len(completed)==len(scope_files)})
    return {"report": str(root / "exports/research_report.md"), "complete_files": len(completed), "selected_files": len(scope_files)}
