from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from .common import digest, dumps, load_json, now, real_author, save_json, typed_id
from .scanner import scan, select_files
from .store import Store

URL_RE = re.compile(r"(?:https?://(?:(?:www|old|np|new)\.)?reddit\.com)?/(?:r/[^/\s)]+/)?comments/([a-z0-9]+)(?:/[^\s<>\])]*?)?(?=[\s<>\])]|$)|https?://redd\.it/([a-z0-9]+)", re.I)
SERIES_CUE = re.compile(r"\b(?:my (?:previous|original|earlier|last) (?:post|update)|original post|previous update|earlier update|next update|follow[- ]?up|update\s*[1-9]|part\s*[1-9]|(?:my|the) (?:first|second|third) post)\b", re.I)


def extract_links(record, original_author=None):
    links = []
    for field in ("title", "selftext", "body"):
        text = record.get(field) or ""
        for match in URL_RE.finditer(text):
            target = typed_id(match[1] or match[2])
            if target == record["thread_id"]:
                continue
            left, right = max(0, match.start()-180), min(len(text), match.end()+180)
            excerpt = text[left:right]
            op = real_author(original_author) and record.get("author") == original_author
            can_support = record["kind"] == "submissions" or op
            supported = can_support and bool(SERIES_CUE.search(excerpt))
            relation = "explicit_series_reference" if supported else "unverified_related_candidate"
            if supported and re.search(r"\b(original|previous|earlier|first)\b", excerpt, re.I):
                relation = "points_to_earlier_post"
            edge = {"source_thread": record["thread_id"], "target_thread": target, "source_record_id": record["typed_id"],
                    "field": field, "raw_start": left, "raw_end": right, "quote": excerpt,
                    "url_start": match.start(), "url_end": match.end(), "url": match.group(),
                    "relationship": relation, "supported": supported,
                    "support_basis": "Explicit URL with a series cue in a submission/OP comment" if supported else "URL alone does not establish same case",
                    "source_created_utc": record.get("created_utc"), "review_status": "requires_relation_review"}
            edge["link_id"] = "l_" + digest(edge)[:20]
            links.append(edge)
    if record.get("crosspost_parent"):
        target = typed_id(record["crosspost_parent"])
        edge = {"source_thread": record["thread_id"], "target_thread": target, "source_record_id": record["typed_id"],
                "field": "crosspost_parent", "relationship": "attributed_crosspost", "supported": True,
                "support_basis": "Explicit crosspost metadata", "review_status": "requires_relation_review"}
        edge["link_id"] = "l_" + digest(edge)[:20]
        links.append(edge)
    return links


def preservation_candidates(records):
    """Run on ALL included posts, including those with accessible archive text."""
    result = []
    posts = [r for r in records if r["kind"] == "submissions"]
    for post in posts:
        candidates = []
        original_text = (post.get("selftext") or "").strip()
        for row in records:
            if row["typed_id"] == post["typed_id"]:
                continue
            for field in ("body", "selftext"):
                text = row.get(field) or ""
                exact_copy = len(original_text) >= 100 and original_text in text
                cue = re.search(r"(?:copy of (?:the )?(?:original|post)|original post (?:by|text)|preserv(?:ed|ation)|in case (?:this|it) (?:gets|is) deleted)", text, re.I)
                # A preservation cue in another thread cannot identify this post by itself.
                attributed = post["typed_id"][3:] in text and "reddit" in text
                if exact_copy or (cue and (row["thread_id"] == post["typed_id"] or attributed)):
                    kind = "subreddit automod in comments" if row.get("author") == "AutoModerator" and row["kind"] == "comments" else "another Redditor in comments" if row["kind"] == "comments" else "another subreddit"
                    candidates.append({"post_id": post["typed_id"], "type": kind, "source_record_id": row["typed_id"], "source_url": row.get("canonical_permalink"),
                                       "attribution": "exact archived original text found" if exact_copy else "preservation cue; copied-author attribution requires review",
                                       "timestamp": row.get("created_utc"), "completeness": "full" if exact_copy else "unknown",
                                       "detection_status": "exact text match" if exact_copy else "candidate_requires_review", "evidence_refs": []})
        result.extend(candidates or [{"post_id": post["typed_id"], "type": "none observed", "detection_status": "Automated text/cue search of collected scope; external copies unsearched"}])
    return result


def group_seeds(records, hits):
    by_id = {r["typed_id"]: r for r in records}
    groups = collections.defaultdict(list)
    for record_id in sorted({h["typed_id"] for h in hits}):
        record = by_id[record_id]
        post = by_id.get(record["thread_id"])
        op_comment = record["kind"] == "comments" and post and real_author(post.get("author")) and record.get("author") == post.get("author")
        # Non-OP narrators can report a different incident in the same thread.
        key = record["thread_id"] if record["kind"] == "submissions" or op_comment else record_id
        groups[key].append(record_id)
    return dict(groups)


def reconstruct(cfg, resume=True):
    root = Path(cfg["data_root"])
    store = Store(cfg, remote=False)
    hits, initial = store.hits(), store.records()
    groups = group_seeds(initial, hits)
    by_id = {r["typed_id"]: r for r in initial}
    queries = {q["query_id"]: q for q in load_json(root / "inputs/keywords.json", [])}
    # Round-robin query-family / record-kind strata; reproducible within each stratum.
    strata = collections.defaultdict(list)
    for gid, seeds in groups.items():
        hs = [h for h in hits if h["typed_id"] in seeds]
        families = sorted({o["sheet"] for h in hs for o in queries[h["query_id"]]["origins"] if o["sheet"] != "All first person searches"})
        strata[(by_id[seeds[0]]["kind"], ",".join(families))].append(gid)
    ordered = []
    while any(strata.values()):
        for key in sorted(strata):
            if strata[key]:
                ordered.append(strata[key].pop(0))
    chosen = ordered[:cfg["context"]["max_cases"]]
    targets = {by_id[s]["thread_id"] for gid in chosen for s in groups[gid] if by_id[s]["thread_id"]}
    store.close()
    manifest = load_json(root / "inputs/source_manifest.json")["files"]
    files = select_files(cfg, manifest, "context")
    # Both collections are batched across all selected cases. Earlier/later explicit
    # members use the same bounded scope; unresolved dates never imply seed month.
    files.sort(key=lambda f: (f["kind"] != "submissions", f["month"], f["path"]))
    iterations, all_links = [], {}
    visited_sets = set()
    for depth in range(cfg["context"]["max_depth"] + 1):
        if not targets or digest(sorted(targets)) in visited_sets:
            break
        visited_sets.add(digest(sorted(targets)))
        run = scan(cfg, stage="context", targets=targets, files=files, resume=resume)
        iterations.append({"depth": depth, "target_ids": sorted(targets), "run_id": run["run_id"], "complete": run["complete"], "stop_reason": run.get("stop_reason")})
        store = Store(cfg, remote=False)
        records = store.records(targets)
        posts = {r["typed_id"]: r for r in records if r["kind"] == "submissions"}
        new_targets = set()
        for record in records:
            for edge in extract_links(record, posts.get(record["thread_id"], {}).get("author")):
                all_links[edge["link_id"]] = edge
                if edge["supported"] and edge["target_thread"] not in targets:
                    new_targets.add(edge["target_thread"])
        store.close()
        if not run["complete"]:
            break
        if not new_targets or depth == cfg["context"]["max_depth"]:
            break
        remaining = cfg["context"]["max_posts"] - len(targets)
        if remaining <= 0:
            break
        targets |= set(sorted(new_targets)[:remaining])
    store = Store(cfg, remote=False)
    records = store.records()
    by_id = {r["typed_id"]: r for r in records}
    if all_links:
        store.db.executemany("INSERT OR REPLACE INTO links VALUES (?,?)", [(k, dumps(v)) for k,v in all_links.items()])
    checkpoints = [json.loads(x[0]) | {"status": x[1]} for x in store.db.execute("SELECT json,status FROM checkpoints WHERE stage='context'").fetchall()]
    graph = collections.defaultdict(set)
    for e in all_links.values():
        if e["supported"]:
            graph[e["source_thread"]].add(e["target_thread"])
            graph[e["target_thread"]].add(e["source_thread"])
    case_paths = []
    for gid, seeds in groups.items():
        thread = by_id[seeds[0]]["thread_id"]
        members, queue = {thread}, [thread]
        while queue:
            node = queue.pop()
            for other in graph[node] - members:
                members.add(other); queue.append(other)
        rows = [r for r in records if r["thread_id"] in members]
        posts = sorted([r for r in rows if r["kind"] == "submissions"], key=lambda r: (r.get("created_utc") or 0, r["typed_id"]))
        earlier_targets = {e["target_thread"] for e in all_links.values() if e["source_thread"] in members and e["relationship"] in ("points_to_earlier_post", "attributed_crosspost")}
        original = next((p for p in posts if p["typed_id"] in earlier_targets), by_id.get(thread))
        incident_id = "i_" + digest([cfg["dataset_revision"], gid])[:20]
        record_ids = {r["typed_id"] for r in rows}
        comments = [r for r in rows if r["kind"] == "comments"]
        complete_paths = {c["path"] for c in checkpoints if c["status"] == "complete" and members <= set(c.get("target_ids", []))}
        incomplete_paths = [f["path"] for f in files if f["path"] not in complete_paths]
        missing_posts = sorted(members - {p["typed_id"] for p in posts})
        coverage = {"selected_for_reconstruction": gid in chosen, "context_scope": cfg["context"],
                    "selected_file_count": len(files), "complete_files_for_entire_case_target_set": len(complete_paths), "incomplete_paths": incomplete_paths,
                    "missing_submission_ids": missing_posts, "retrieved_comments": len(comments),
                    "missing_parent_ids": sorted({r["parent_id"] for r in comments if r.get("parent_id") and r["parent_id"] not in record_ids}),
                    "deleted_or_removed_comments": sum(r.get("body") in ("[deleted]", "[removed]") for r in comments),
                    "archived_num_comments_by_post": {p["typed_id"]: p.get("num_comments") for p in posts},
                    "all_available_comments_in_declared_scope": bool(not incomplete_paths and not missing_posts and gid in chosen),
                    "complete_case": False, "case_completeness_reason": "Archive/window limits; undetected follow-ups and external/live comments cannot be ruled out",
                    "event_order_status": "dates preserved; before/after discovery unknown until evidence-reviewed event time", "iterations": iterations}
        bundle = {"incident_id": incident_id, "provisional_grouping_key": gid, "seed_record_ids": seeds, "seed_thread_id": thread,
                  "original_post_id": original["typed_id"] if original and original["kind"] == "submissions" else None,
                  "original_resolution_status": "provisional seed thread" if original else "unresolved",
                  "members": [{"post_id": p["typed_id"], "created_utc": p.get("created_utc"), "relative_to_discovery": "unknown"} for p in posts],
                  "record_ids": sorted(record_ids), "records": rows, "comments_by_thread": {tid: [c["typed_id"] for c in comments if c["thread_id"] == tid] for tid in sorted(members)},
                  "series_links": [e for e in all_links.values() if e["source_thread"] in members],
                  "preservation_candidates": preservation_candidates(rows), "coverage": coverage,
                  "keyword_hits": [h for h in hits if h["typed_id"] in seeds], "assembled_at": now()}
        bundle["content_hash"] = digest({"records": [{k:v for k,v in r.items() if k != "retrieved_at"} for r in rows], "coverage": coverage, "seeds": seeds})
        path = root / "cases" / (incident_id + ".json")
        save_json(path, bundle)
        case_paths.append(str(path))
    save_json(root / "cases/index.json", {"case_paths": case_paths, "selected_group_ids": chosen, "deferred_group_ids": ordered[len(chosen):],
                "grouping_note": "Provisional collection units. Non-OP comments remain separate until incident reconciliation; these are not confirmed incident counts.",
                "iterations": iterations})
    store.close()
    return {"case_bundles": len(case_paths), "selected_for_reconstruction": len(chosen), "target_threads": len(targets), "iterations": iterations}


def demonstrate_joins(cfg):
    root = Path(cfg["data_root"])
    samples = load_json(root / "inspection/samples.json")
    first = next(s for s in samples if s["kind"] == "comments" and s["period"] == "early")
    targets = sorted({typed_id(r["link_id"]) for r in first["rows"]})
    manifest = load_json(root / "inputs/source_manifest.json")["files"]
    files = [f for f in manifest if f["month"] == first["month"]]
    run = scan(cfg, "context", targets=set(targets), files=files, resume=True)
    store = Store(cfg, remote=False)
    rows = store.records(targets)
    posts = {r["typed_id"] for r in rows if r["kind"] == "submissions"}
    result = {"purpose": "Retrieval experiment, not discovered re-identification cases", "scope": first["month"],
              "target_ids": targets, "found_submission_ids": sorted(posts), "failed_submission_joins": sorted(set(targets)-posts),
              "comments_per_target": dict(collections.Counter(r["thread_id"] for r in rows if r["kind"] == "comments")),
              "returned_record_ids": [r["typed_id"] for r in rows], "run_id": run["run_id"], "complete_selected_shards": run["complete"]}
    save_json(root / "inspection/join_demonstration.json", result)
    store.close()
    return result
