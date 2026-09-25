from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from .common import digest, dumps, load_json, now, save_json
from .schema import Annotation, INTENTS, EVIDENCE_TYPES, OUTCOMES, RELATIONSHIPS, SUBTYPES, PRESERVATION_TYPES
from .store import Store

HEADERS = ["id", "permalink", "title", "Confirmed URL", "Account age (@ time of posting)",
    "# of other comments (@ time of posting)", "# of other posts (@ time of posting)",
    "# subreddits active in (@ time of posting, including original subreddit)", "Throwaway/One time Use", "Deleted Account?",
    "Weekly Visitors (Lurkers) at posting", "Weekly Contributors (Posters) at posting", "Upvote/downvote counts", "Comments exposure metric", "Traffic exposure metric",
    "Deleted Post?", "Post Intent", "url", "Post ID", "OG post date", "OG Reddit", "OG Post Title", "OP POST", "OP Post Part 2 (if needed)",
    "RELEVANT COMMENTS WHERE RE-IDENTIFICATION OCCURRED", "Who is reporting re-identification?", "When was it found?", "How was it found?", "Who found it originally?",
    "Notes related to discovery", "Part of a series? Total # of posts, updates/linked posts prior to re-identification", "Repercussions/outcomes", "Where was deleted post preserved",
    "author", "score", "upvote_ratio", "num_comments", "created_utc", "link_flair_text", "is_self", "over_18", "selftext"]
MAPPINGS = ["seed.id", "seed.canonical_permalink", "seed.title", "evidence[].permalink", "metrics.account_age_seconds",
    "metrics.prior_comments_lifetime", "metrics.prior_posts_lifetime", "metrics.distinct_active_subreddits_lifetime", "account.requested_type", "account.status",
    "metrics.weekly_visitors_at_posting", "metrics.weekly_contributors_at_posting", "metrics.upvotes + metrics.downvotes", "collection_coverage.retrieved_comments",
    "metrics.traffic_at_posting", "original.status", "original.primary_intent", "original_record.url", "original.post_id", "original.created_utc", "original.subreddit",
    "original.title", "original.full_text[0:14000]", "original.full_text[14000:28000]", "evidence[].quote", "actors.reporters", "discovery.original_time_expression",
    "discovery.chain", "actors.finders", "discovery.notes", "series", "outcomes", "preservation", "original_record.author", "original_record.score",
    "original_record.upvote_ratio", "original_record.num_comments", "original.created_utc", "original_record.link_flair_text", "original_record.is_self",
    "original_record.over_18", "original.full_text"]
ADDITIONAL = ["Confirmed re-identification", "Review status", "Incident ID", "Original resolution status", "Evidence type", "Finder relationship requested category",
    "Finder graph distance observed", "Finder relationship subtypes", "Evidence references", "Account observation date", "Post observation date", "Missingness reasons",
    "Collection coverage", "Review coverage", "Identity connection type", "Voluntary disclosure", "Canonical case file", "Annotation file", "Triage flags",
    "Candidate disposition", "Reviewer label", "Reviewer notes", "Full annotation JSON"]


def excel_literal(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def text_parts(value, length=14000):
    return [value[i:i+length] for i in range(0, len(value), length)] or [""]


def csv_write(path, headers, rows):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([excel_literal(dumps(v) if isinstance(v, (list, dict)) else v) for v in row])


def workbook_parts(tables, max_rows):
    """Partition every large table without dropping rows; repeat dictionaries."""
    repeated = {'Summary', 'Codebook', 'Field availability'}
    count = max(1, max((len(t['rows']) + max_rows - 1)//max_rows for n,t in tables.items() if n not in repeated))
    for index in range(count):
        part, ranges = {}, {}
        for name, table in tables.items():
            start = 0 if name in repeated else index*max_rows
            end = len(table['rows']) if name in repeated else min(start+max_rows, len(table['rows']))
            part[name] = {'headers': table['headers'], 'rows': table['rows'][start:end]}
            ranges[name] = {'first_global_data_row': start+1 if start < end else None, 'last_global_data_row': end if start < end else None}
        part['Summary'] = {'headers': tables['Summary']['headers'], 'rows': tables['Summary']['rows'] + [
            ['Workbook part', f'{index+1} of {count}'],
            ['Partition interpretation', 'Tables are partitioned independently. All rows are included across workbook parts. Global data rows exclude headers; see workbook_manifest.json and full CSV files.'],
            ['Text references', 'Text parts source_cell uses the global CSV/export row including its header; it is not a row number within a later workbook part.'],
        ]}
        yield index+1, part, ranges


def export(cfg, workbook=True):
    root = Path(cfg["data_root"])
    out = root / "exports"
    out.mkdir(parents=True, exist_ok=True)
    store = Store(cfg, remote=False)
    records = store.records()
    by_id = {r["typed_id"]: r for r in records}
    hits = store.hits()
    annotations = [json.loads(row[0]) for row in store.db.execute("SELECT json FROM annotations ORDER BY incident_id").fetchall()]
    annotations.sort(key=lambda a: (a['review_status'].startswith('pending'), {'Yes':0,'Unsure':1,'No':2}[a['confirmed_reidentification']], a['original']['post_id'] is None, a['incident_id']))
    checkpoints = [json.loads(row[0]) | {"status": row[1], "scanned": row[2]} for row in store.db.execute("SELECT json,status,scanned FROM checkpoints ORDER BY path,stage").fetchall()]
    links = [json.loads(row[0]) for row in store.db.execute("SELECT json FROM links").fetchall()]
    dictionary = []
    for h, mapping in zip(HEADERS, MAPPINGS):
        availability = "extra evidence required" if mapping.startswith(("account.", "evidence", "actors.", "discovery.", "outcomes", "preservation", "series")) else "derived" if mapping.startswith("collection_") else "direct archive field / may be missing"
        if mapping.startswith("metrics.") or h in ("is_self", "upvote_ratio"):
            availability = "unavailable in inspected schema; null"
        dictionary.append([h, mapping, availability, "Seed fields describe discovery record. Original fields remain provisional until original resolution. Unknown is blank with missingness reason."])
    extra_mappings = ['confirmed_reidentification','review_status','incident_id','original_resolution_status','evidence[].content_type',
        'actors.finder_relationship_requested_category','actors.finder_graph_distance_observed','actors.finder_relationship_subtypes','evidence[].evidence_id',
        'account.status_observation_date','original.status_observed_at','missingness','collection_coverage','review_coverage','identity_connection_type','voluntary_disclosure',
        'cases/{incident_id}.json','annotations/{incident_id}.json','seed.triage_flags','derived from review_status and confirmed_reidentification',
        'human adjudication input (not yet supplied)','human adjudication notes (not yet supplied)','Annotation (complete schema)']
    for h, mapping in zip(ADDITIONAL,extra_mappings):
        dictionary.append([h, mapping, "project-derived", "Review labels are not ground truth"])
    rows, evidence_rows, incident_rows = [], [], []
    for a in annotations:
        original = a["original"]
        op = by_id.get(original["post_id"], {})
        evidence = a["evidence"]
        fulltext = original.get("full_text") or ""
        parts = text_parts(fulltext)
        for seed_id in a["seed_record_ids"]:
            seed = by_id.get(seed_id, {})
            row = [seed.get("id"), seed.get("canonical_permalink"), seed.get("title"), evidence[0].get("permalink") if evidence else None,
                   a["metrics"].get("account_age_seconds"), a["metrics"].get("prior_comments_lifetime"), a["metrics"].get("prior_posts_lifetime"),
                   a["metrics"].get("distinct_active_subreddits_lifetime"), a["account"]["requested_type"], a["account"]["status"],
                   None, None, None, a["collection_coverage"].get("retrieved_comments") if a["collection_coverage"].get("comments_collected", True) else None, None,
                   original["status"], original["primary_intent"], op.get("url"), original["post_id"], original["created_utc"], original["subreddit"], original["title"],
                   parts[0], parts[1] if len(parts) > 1 else None, [e["quote"] for e in evidence], a["actors"]["reporters"], a["discovery"]["original_time_expression"],
                   a["discovery"]["chain"], a["actors"]["finders"], a["discovery"]["notes"], a["series"], a["outcomes"], a["preservation"],
                   op.get("author"), op.get("score"), op.get("upvote_ratio"), op.get("num_comments"), original["created_utc"], op.get("link_flair_text"),
                   op.get("is_self"), op.get("over_18"), fulltext]
            row += [a["confirmed_reidentification"], a["review_status"], a["incident_id"], a["original_resolution_status"], [e["content_type"] for e in evidence],
                    a["actors"]["finder_relationship_requested_category"], a["actors"]["finder_graph_distance_observed"], a["actors"]["finder_relationship_subtypes"],
                    [e["evidence_id"] for e in evidence], a["account"]["status_observation_date"], original["status_observed_at"], a["missingness"],
                    a["collection_coverage"], a["review_coverage"], a["identity_connection_type"], a["voluntary_disclosure"],
                    "cases/" + a["incident_id"] + ".json", "annotations/" + a["incident_id"] + ".json", seed.get("triage_flags", []),
                    "Keyword candidate; qualification pending" if a["review_status"].startswith("pending") else "Reported event" if a["confirmed_reidentification"] == "Yes" else "Reviewed " + a["confirmed_reidentification"], None, None, a]
            assert len(row) == len(HEADERS + ADDITIONAL)
            rows.append(row)
        incident_rows.append([a["incident_id"], a["confirmed_reidentification"], a["review_status"], original["post_id"], a["seed_record_ids"], a["rationale"], a["original_resolution_status"], a["series"]["observed_count"], a["collection_coverage"], None, None])
        for e in evidence:
            evidence_rows.append([a["incident_id"], e["evidence_id"], e["quote"], e["raw_start"], e["raw_end"], e["source_record_id"], e["thread_id"], e["permalink"], e["source_field"], e["reporting_username"], e["role_relative_to_original_op"], e["record_created_utc"], e["edit_timestamp"], e["event_time_expression"], e["content_type"], e["attribution"]])
    # A distinct post catalog prevents counting seed records as unique submissions.
    post_catalog = [[r["typed_id"], r.get("canonical_permalink"), r.get("subreddit"), r.get("title"), r.get("selftext"), r.get("created_utc"), r.get("author"), r["source"], r.get("triage_flags", [])] for r in records if r["kind"] == "submissions"]
    queries = {q["query_id"]: q for q in load_json(root / "inputs/keywords.json", [])}
    tables = {
        "Review": {"headers": HEADERS + ADDITIONAL, "rows": rows},
        "Incidents": {"headers": ["incident_id", "confirmed_reidentification", "review_status", "original_post_id", "seed_record_ids", "rationale", "original_resolution", "observed_posts", "coverage", "Reviewer label", "Reviewer notes"], "rows": incident_rows},
        "Posts": {"headers": ["post_id", "permalink", "subreddit", "title", "full_selftext", "created_utc", "author", "source", "triage_flags"], "rows": post_catalog},
        "Evidence": {"headers": ["incident_id", "evidence_id", "quote", "raw_start", "raw_end", "source_record_id", "thread_id", "permalink", "source_field", "reporter_username", "role", "record_created_utc", "edit_timestamp", "event_time_expression", "content_type", "attribution"], "rows": evidence_rows},
        "Comments": {"headers": ["comment_id", "thread_id", "parent_id", "body", "author", "created_utc", "source", "permalink"], "rows": [[r["typed_id"], r["thread_id"], r.get("parent_id"), r.get("body"), r.get("author"), r.get("created_utc"), r["source"], r.get("canonical_permalink")] for r in records if r["kind"] == "comments"]},
        "Series links": {"headers": ["link_id", "source_thread", "target_thread", "relationship", "supported", "source_record_id", "quote", "review_status"], "rows": [[e.get(k) for k in ("link_id", "source_thread", "target_thread", "relationship", "supported", "source_record_id", "quote", "review_status")] for e in links]},
        "Keyword hits": {"headers": ["hit_id", "record_id", "thread_id", "query_id", "field", "raw_start", "raw_end", "exact_match", "context", "query_memberships", "source"], "rows": [[h["hit_id"], h["typed_id"], h["thread_id"], h["query_id"], h["field"], h["start"], h["end"], h["quote"], h["context"], queries[h["query_id"]]["origins"], h["source"]] for h in hits]},
        "Codebook": {"headers": ["field", "allowed_label", "authority"], "rows": [[name, label, "Project rubric; see codebook.md for paper crosswalk"] for name, options in [("post_intent", INTENTS), ("evidence_type", EVIDENCE_TYPES), ("outcome", OUTCOMES), ("relationship", RELATIONSHIPS), ("relationship_subtype", SUBTYPES), ("preservation", PRESERVATION_TYPES), ("confirmation", ["Yes", "No", "Unsure"])] for label in options]},
        "Field availability": {"headers": ["export_column", "canonical_field", "availability", "interpretation"], "rows": dictionary},
        "Run coverage": {"headers": ["stage", "shard", "status", "records_returned", "seconds", "payload_bytes", "peak_rss_bytes", "scope", "target_hash", "error"], "rows": [[c.get(k) for k in ("stage", "path", "status", "scanned", "elapsed_seconds", "payload_bytes", "peak_rss_bytes", "scope", "target_hash", "error")] for c in checkpoints]},
    }
    total_scanned = sum(c["scanned"] for c in checkpoints if c.get("stage") == "discovery" and c.get("status") == "complete")
    summary = {"Exported at UTC": now(), "Completed discovery checkpoint rows (scopes may overlap)": total_scanned,
               "Unique keyword-matching records": len({h["typed_id"] for h in hits}), "Unique keyword-hit threads": len({h["thread_id"] for h in hits}),
               "Provisional case units": len(annotations), "Reviewed Yes": sum(a["confirmed_reidentification"] == "Yes" for a in annotations),
               "Reviewed No": sum(a["confirmed_reidentification"] == "No" for a in annotations), "Unsure or awaiting review": sum(a["confirmed_reidentification"] == "Unsure" for a in annotations),
               "Coverage note": "All matches in successfully processed manifest files. No claim of full Reddit coverage. Case units are provisional, not adjudicated incidents.",
               "Comment policy": "Comment-text discovery is separate from optional thread reconstruction. Counts may represent seed comments only.",
               "Text preservation": "CSV and canonical Parquet/JSON retain full text. Long Excel cells reference Text parts. Times are UTC Unix seconds unless labeled otherwise.",
               "Formula safety": "Potential formula prefixes are escaped in CSV/XLSX. Canonical records preserve exact source text.",
               "Model status": "Configured" if cfg["model"].get("name") else "No classification model configured; unreviewed matches remain candidates."}
    tables = {"Summary": {"headers": ["Measure", "Value"], "rows": list(map(list, summary.items()))}, **tables}
    full_parts = []
    for name, table in tables.items():
        csv_write(out / (name.lower().replace(" ", "_") + ".csv"), table["headers"], table["rows"])
        for row_num, row in enumerate(table["rows"], 2):
            for col_num, value in enumerate(row):
                if isinstance(value, (dict, list)):
                    value = dumps(value)
                if isinstance(value, str) and len(value.encode("utf-16-le"))//2 > 30000:
                    ref = f"{name}!row{row_num}:{table['headers'][col_num]}"
                    for i, part in enumerate(text_parts(value), 1):
                        full_parts.append([ref, i, len(text_parts(value)), part, "See full CSV and canonical case/record files"])
                    value = "Full value in Text parts: " + ref
                row[col_num] = value
    tables["Text parts"] = {"headers": ["source_cell", "part", "total_parts", "text", "canonical_reference"], "rows": full_parts}
    csv_write(out / "text_parts.csv", tables["Text parts"]["headers"], full_parts)
    # CSV/JSONL are the complete machine-readable export. XLSX inputs are
    # partitioned to bound artifact-tool memory on the full archive result set.
    save_json(out / "export_summary.json", summary)
    with (out / "annotations.jsonl").open("w", encoding="utf-8") as f:
        for a in annotations:
            f.write(dumps(a) + "\n")
    store.close()
    workbooks = []
    if workbook:
        for part_number, part, ranges in workbook_parts(tables, cfg['export'].get('max_rows_per_workbook', 2000)):
            stem = 'research_review' if part_number == 1 else f'research_review_{part_number:03d}'
            input_path = out / 'workbook_data.json'
            save_json(input_path, part)
            target = out / (stem + '.xlsx')
            subprocess.run([cfg["export"]["node_executable"], str(Path(__file__).resolve().parent.parent / "tools/export-workbook.mjs"), str(input_path), str(target)], check=True)
            workbooks.append({'path':str(target), 'part':part_number, 'table_ranges':ranges})
            save_json(out / 'workbook_manifest.json', {'complete':False, 'generated_at':now(), 'workbooks':workbooks})
        save_json(out / 'workbook_manifest.json', {'complete':True, 'generated_at':now(), 'workbooks':workbooks})
    return {"review_rows": len(rows), "incidents": len(incident_rows), "directory": str(out), "workbook": str(out / "research_review.xlsx") if workbook else None, 'workbook_count':len(workbooks)}
