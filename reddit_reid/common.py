from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def digest(value):
    return hashlib.sha256((value if isinstance(value, bytes) else dumps(value).encode("utf-8"))).hexdigest()


def save_json(path, value, durable=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)
        f.flush()
        if durable:
            os.fsync(f.fileno())
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (attempt+1))


def load_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_config(path):
    path = Path(path).resolve()
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["config_path"] = str(path)
    for key in ("data_root", "keyword_workbook"):
        cfg[key] = str((path.parent / cfg[key]).resolve())
    root = Path(cfg["data_root"])
    for folder in ("inputs", "state", "records/submissions", "records/comments", "cases", "exports", "cache/shards", "tmp", "logs", "inspection", "annotations"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(root / "cache/huggingface")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    return cfg


def typed_id(value, kind="t3"):
    if value is None:
        return None
    value = str(value).strip().lower()
    m = re.fullmatch(r"(?:(t[13])_)?([a-z0-9]+)", value)
    if not m:
        raise ValueError(f"Invalid Reddit ID: {value!r}")
    return (m.group(1) or kind) + "_" + m.group(2)


def real_author(value):
    return bool(value and value not in ("[deleted]", "[removed]", "AutoModerator"))


def permalink(record):
    tid = record.get("thread_id") or record.get("typed_id")
    if not tid:
        return None
    base = f"https://www.reddit.com/comments/{tid.removeprefix('t3_')}/"
    return base + "_/" + record["typed_id"][3:] + "/" if record.get("kind") == "comments" else base


def disk_usage(root):
    return sum(p.stat().st_size for p in Path(root).rglob("*") if p.is_file())


class BudgetStop(RuntimeError):
    pass


def check_disk(cfg):
    root = Path(cfg["data_root"])
    used = disk_usage(root)
    free = shutil.disk_usage(root).free
    if used >= cfg["resources"]["disk_bytes"] or free < cfg["resources"]["minimum_free_bytes"]:
        raise BudgetStop(f"Disk budget: used={used}, free={free}")
    return used


def historical_metrics(original, records, account_created_utc=None):
    """Observed activity is a lower bound; never merge deleted identities."""
    author = original.get("author")
    ts = original.get("created_utc")
    eligible = [r for r in records if real_author(author) and r.get("author") == author
                and ts is not None and r.get("created_utc") is not None and r["created_utc"] < ts]
    return {
        "account_age_seconds": ts - account_created_utc if ts is not None and account_created_utc is not None and ts >= account_created_utc else None,
        "observed_prior_comments_lower_bound": sum(r["kind"] == "comments" for r in eligible) if real_author(author) else None,
        "observed_prior_posts_lower_bound": sum(r["kind"] == "submissions" for r in eligible) if real_author(author) else None,
        "observed_active_subreddits_including_target": len({r.get("subreddit") for r in eligible} | {original.get("subreddit")}) if real_author(author) and original.get("subreddit") else None,
        "prior_comments_lifetime": None, "prior_posts_lifetime": None,
        "distinct_active_subreddits_lifetime": None,
        "weekly_visitors_at_posting": None, "weekly_contributors_at_posting": None,
        "traffic_at_posting": None, "upvotes": None, "downvotes": None,
        "coverage": "selected case records only; not an author-history census",
        "missing_reason": "not_in_source",
    }
