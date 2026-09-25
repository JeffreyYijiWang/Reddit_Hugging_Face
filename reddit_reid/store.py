from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .common import digest, dumps, now


class Store:
    def __init__(self, cfg, remote=True):
        self.root = Path(cfg["data_root"])
        self.db = duckdb.connect(str(self.root / "state/research.duckdb"))
        self.db.execute("SET memory_limit = ?", [cfg["resources"]["memory_limit"]])
        self.db.execute("SET threads = ?", [cfg["resources"]["threads"]])
        self.db.execute("SET temp_directory = ?", [str(self.root / "tmp")])
        self.db.execute("SET max_temp_directory_size = ?", [str(cfg["resources"]["spill_bytes"]) + "B"])
        self.db.execute("SET preserve_insertion_order = true")
        extension_dir = self.root / "cache/extensions"
        extension_dir.mkdir(exist_ok=True, parents=True)
        self.db.execute("SET extension_directory = ?", [str(extension_dir)])
        if remote:
            try:
                self.db.execute("LOAD httpfs")
            except duckdb.Error:
                self.db.execute("INSTALL httpfs")
                self.db.execute("LOAD httpfs")
            self.db.execute("SET http_timeout = 60")
            self.db.execute("SET http_retries = 1")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_manifest(path VARCHAR PRIMARY KEY, json VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS query_definitions(query_id VARCHAR PRIMARY KEY, json VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS records(typed_id VARCHAR PRIMARY KEY, kind VARCHAR, thread_id VARCHAR, content_hash VARCHAR, json VARCHAR, canonical_file VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS hits(hit_id VARCHAR PRIMARY KEY, typed_id VARCHAR, query_id VARCHAR, json VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS checkpoints(key VARCHAR PRIMARY KEY, stage VARCHAR, path VARCHAR, status VARCHAR, scanned BIGINT, json VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS annotations(incident_id VARCHAR PRIMARY KEY, json VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS links(link_id VARCHAR PRIMARY KEY, json VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs(run_id VARCHAR PRIMARY KEY, json VARCHAR)")

    def bulk(self, table, rows, replace=True):
        if not rows:
            return
        allowed = {"records", "hits", "source_manifest", "query_definitions", "annotations", "links"}
        if table not in allowed:
            raise ValueError("Invalid table")
        self.db.register("incoming_batch", pa.Table.from_pylist(rows))
        try:
            self.db.execute("INSERT OR " + ("REPLACE" if replace else "IGNORE") + " INTO " + table + " SELECT * FROM incoming_batch")
        finally:
            self.db.unregister("incoming_batch")

    def put_records(self, records):
        for kind in ("comments", "submissions"):
            subset = {r["typed_id"]: r for r in records if r["kind"] == kind}
            if not subset:
                continue
            # Immutable content-addressed chunks, written before the catalog commit.
            rows = [{"typed_id": r["typed_id"], "thread_id": r["thread_id"], "json": dumps(r)} for r in subset.values()]
            key = digest(rows)
            final = self.root / "records" / kind / (key + ".parquet")
            if not final.exists():
                tmp = final.with_suffix(".parquet.partial")
                pq.write_table(pa.Table.from_pylist(rows), tmp, compression="zstd")
                with tmp.open('rb+') as completed_file:
                    os.fsync(completed_file.fileno())
                assert pq.ParquetFile(tmp).metadata.num_rows == len(rows)
                os.replace(tmp, final)
            self.bulk("records", [dict(typed_id=r["typed_id"], kind=kind, thread_id=r["thread_id"], content_hash=digest(r), json=dumps(r), canonical_file=str(final.relative_to(self.root))) for r in subset.values()])

    def recover(self):
        """Catalog durable orphan chunks; incomplete writes remain inspectable."""
        known = {row[0] for row in self.db.execute("SELECT DISTINCT canonical_file FROM records").fetchall()}
        recovered = 0
        for path in sorted((self.root / "records").rglob("*.parquet")):
            if str(path.relative_to(self.root)) in known:
                continue
            for row in pq.read_table(path).to_pylist():
                r = json.loads(row["json"])
                self.db.execute("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?)", [r["typed_id"], r["kind"], r["thread_id"], digest(r), dumps(r), str(path.relative_to(self.root))])
                recovered += 1
        return {"recovered_rows": recovered, "partial_files": [str(p) for p in (self.root / "records").rglob("*.partial")]}

    def put_hits(self, hits):
        if hits:
            self.bulk("hits", [dict(hit_id=h["hit_id"], typed_id=h["typed_id"], query_id=h["query_id"], json=dumps(h)) for h in hits], replace=False)

    def checkpoint(self, key, stage, path, status, scanned, detail):
        self.db.execute("INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?,?)", [key, stage, path, status, scanned, dumps(detail)])

    def completed(self, key):
        row = self.db.execute("SELECT status FROM checkpoints WHERE key=?", [key]).fetchone()
        return bool(row and row[0] == "complete")

    def records(self, thread_ids=None):
        sql = "SELECT json FROM records"
        params = []
        if thread_ids is not None:
            sql += " WHERE thread_id IN (SELECT unnest(?))"
            params = [list(thread_ids)]
        return [json.loads(row[0]) for row in self.db.execute(sql, params).fetchall()]

    def hits(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT json FROM hits ORDER BY hit_id").fetchall()]

    def close(self):
        self.db.close()
