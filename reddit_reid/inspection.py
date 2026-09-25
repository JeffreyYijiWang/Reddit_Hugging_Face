from __future__ import annotations

import collections
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from .common import BudgetStop, dumps, load_json, now, save_json
from .transport import Ledger, Relay
from .store import Store


def inventory(cfg, ledger):
    root = Path(cfg["data_root"])
    path = root / "inputs/source_manifest.json"
    existing = load_json(path)
    if existing and existing["revision"] == cfg["dataset_revision"]:
        return existing
    repo, revision = cfg["dataset_repo"], cfg["dataset_revision"]
    info, _ = ledger.json_get(f"https://huggingface.co/api/datasets/{repo}/revision/{revision}")
    if not re.fullmatch(r"[0-9a-f]{40}", info["sha"]):
        raise ValueError("Expected immutable revision")
    revision = info["sha"]
    url = f"https://huggingface.co/api/datasets/{repo}/tree/{revision}"
    entries = []
    params = {"recursive": "true", "limit": 1000}
    while url:
        if urlparse(url).netloc != "huggingface.co":
            raise ValueError("Unexpected pagination host")
        page, links = ledger.json_get(url, params)
        entries.extend(page)
        url = links.get("next", {}).get("url")
        params = None
    files = []
    for e in entries:
        m = re.fullmatch(r"data/(comments|submissions)/(\d{4})/(\d{2})/[^/]+\.parquet", e["path"])
        if e["type"] == "file" and m:
            files.append({"kind": m[1], "path": e["path"], "month": m[2] + "-" + m[3], "bytes": e["size"],
                          "repo": repo, "revision": revision,
                          "url": f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{quote(e['path'])}",
                          "row_count": None, "schema": None, "inspection_status": "inventory_only"})
    files.sort(key=lambda f: (f["kind"], f["path"]))
    result = {"repo": repo, "revision": revision, "retrieved_at": now(), "files": files,
              "other_files": [e for e in entries if e["type"] == "file" and not e["path"].endswith(".parquet")],
              "configs_from_card": info.get("cardData", {}).get("configs"), "tree_complete": True}
    save_json(root / "inspection/repository_info.json", info)
    save_json(root / "inspection/repository_tree.json", entries)
    save_json(path, result)
    return result


def describe(db, url):
    return [{"name": r[0], "type": r[1]} for r in db.execute("DESCRIBE SELECT * FROM read_parquet(?)", [url]).fetchall()]


def inspect(cfg):
    ledger = Ledger(cfg)
    manifest = inventory(cfg, ledger)
    summary = {}
    for kind in ("comments", "submissions"):
        files = [f for f in manifest["files"] if f["kind"] == kind]
        months = sorted({f["month"] for f in files})
        summary[kind] = {"shards": len(files), "bytes": sum(f["bytes"] for f in files), "first_month": months[0] if months else None,
                         "last_month": months[-1] if months else None, "months": months}
    summary["comments_only_months"] = sorted(set(summary["comments"]["months"]) - set(summary["submissions"]["months"]))
    summary["submissions_only_months"] = sorted(set(summary["submissions"]["months"]) - set(summary["comments"]["months"]))
    root = Path(cfg["data_root"])
    save_json(root / "inspection/inventory_summary.json", summary)
    store = Store(cfg)
    relay = Relay(cfg, manifest["files"], ledger)
    samples = []
    started = time.monotonic()
    try:
        for kind in ("comments", "submissions"):
            months = summary[kind]["months"]
            for label, month in zip(("early", "middle", "recent"), [months[0], months[len(months)//2], months[-1]]):
                ledger.check_time()
                file = next(f for f in manifest["files"] if f["kind"] == kind and f["month"] == month)
                prior = next((s for s in load_json(root / "inspection/samples.json", []) if s["path"] == file["path"]), None)
                if prior:
                    samples.append(prior); continue
                start, before = time.monotonic(), ledger.data["payload_bytes"]
                try:
                    url = relay.url(file)
                    schema = describe(store.db, url)
                    file["schema"] = schema
                    file["row_count"] = store.db.execute("SELECT count(*) FROM read_parquet(?)", [url]).fetchone()[0]
                    columns = [c["name"] for c in schema]
                    selected = [c for c in ("id", "author", "subreddit", "title", "selftext", "body", "created_utc", "link_id", "parent_id", "score", "num_comments", "url", "permalink", "is_self") if c in columns]
                    sql = "SELECT " + ",".join('"' + c + '"' for c in selected) + " FROM read_parquet(?) LIMIT 5"
                    cursor = store.db.execute(sql, [url])
                    rows = [dict(zip(selected, r)) for r in cursor.fetchall()]
                    text_fields = [c for c in ("body", "title", "selftext") if c in columns]
                    stats = {field: dict(collections.Counter("null" if r.get(field) is None else "empty" if not r[field] else "placeholder" if r[field] in ("[deleted]", "[removed]") else "text" for r in rows)) for field in text_fields}
                    sample = {"kind": kind, "period": label, "month": month, "path": file["path"], "revision": manifest["revision"], "sql": sql,
                              "schema": schema, "shard_row_count": file["row_count"], "rows": rows, "text_statistics_sample_only": stats,
                              "subreddit_frequencies_sample_only": dict(collections.Counter(r.get("subreddit") for r in rows)),
                              "elapsed_seconds": time.monotonic()-start, "payload_bytes": ledger.data["payload_bytes"]-before}
                    file["inspection_status"] = "sampled"
                except Exception as exc:
                    sample = {"kind": kind, "path": file["path"], "period": label, "error": str(exc)}
                    file["inspection_status"] = "failed"
                samples.append(sample)
                save_json(root / "inspection/samples.json", samples)
                save_json(root / "inputs/source_manifest.json", manifest)
        store.bulk("source_manifest", [dict(path=f["path"], json=dumps(f)) for f in manifest["files"]])
        save_json(root / "inspection/duckdb_settings.json", {"version": store.db.execute("SELECT version()").fetchone()[0],
                    "settings": store.db.execute("SELECT name,value FROM duckdb_settings() WHERE name IN ('memory_limit','threads','temp_directory','max_temp_directory_size','http_timeout','http_retries')").fetchall()})
    finally:
        ledger.data["query_seconds"] += time.monotonic()-started
        ledger.flush(); relay.close(); store.close()
    return summary
