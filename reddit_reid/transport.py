"""Allowlisted HTTP range relay with a persistent HTTP payload ledger.

DuckDB queries localhost; the relay only serves immutable manifest entries.
Bytes mean upstream response-body bytes consumed, excluding headers/TLS/TCP.
Content-length reservation prevents starting requests over the cap. Read-ahead
in OS/network buffers is not measured, so this is not a wire-byte guarantee.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
import truststore

truststore.inject_into_ssl()

from .common import BudgetStop, load_json, now, save_json


class Ledger:
    def __init__(self, cfg):
        self.cfg = cfg
        self.path = Path(cfg["data_root"]) / "state/resource_ledger.json"
        self.data = load_json(self.path, {"payload_bytes": 0, "query_seconds": 0, "requests": 0, "errors": [], "created": now()})
        self.lock = threading.RLock()
        self.reserved = 0

    def check_time(self):
        if self.data["query_seconds"] >= self.cfg["resources"]["max_query_seconds"]:
            raise BudgetStop("Cumulative seven-hour query limit reached")

    def reserve(self, amount):
        with self.lock:
            if self.data["payload_bytes"] + self.reserved + amount > self.cfg["resources"]["network_bytes"]:
                raise BudgetStop("HTTP payload budget reached")
            self.reserved += amount

    def add(self, amount, source_path=None):
        with self.lock:
            self.reserved -= amount
            self.data["payload_bytes"] += amount
            if source_path:
                by_source = self.data.setdefault('payload_bytes_by_source',{})
                by_source[source_path] = by_source.get(source_path,0)+amount

    def flush(self):
        with self.lock:
            save_json(self.path, self.data)

    def json_get(self, url, params=None):
        self.check_time()
        start = time.monotonic()
        try:
            for attempt in range(3):
                r = requests.get(url, params=params, timeout=45)
                self.reserve(len(r.content))
                self.add(len(r.content))
                self.data["requests"] += 1
                if r.status_code not in (429, 500, 502, 503, 504):
                    r.raise_for_status()
                    return r.json(), r.links
                time.sleep(min(2 ** attempt, 4))
            r.raise_for_status()
        finally:
            self.data["query_seconds"] += time.monotonic() - start
            self.flush()


class Relay:
    def __init__(self, cfg, manifest, ledger):
        self.cfg, self.ledger = cfg, ledger
        self.allowed = {str(i): f["url"] for i, f in enumerate(manifest)}
        self.index = {f["path"]: str(i) for i, f in enumerate(manifest)}
        self.paths = {str(i): f['path'] for i,f in enumerate(manifest)}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_HEAD(self):
                self.serve(True)

            def do_GET(self):
                self.serve(False)

            def serve(self, head):
                url = owner.allowed.get(self.path.lstrip("/").split("?")[0])
                if url is None:
                    self.send_error(404); return
                received, reservation, started = 0, 0, False
                try:
                    if time.monotonic() >= getattr(owner, "deadline", float("inf")):
                        raise BudgetStop("Query deadline reached")
                    headers = {"Accept-Encoding": "identity", "User-Agent": "reddit-reid-research/0.1"}
                    if "Range" in self.headers:
                        headers["Range"] = self.headers["Range"]
                    method = requests.head if head else requests.get
                    with method(url, headers=headers, stream=True, allow_redirects=True,
                                timeout=owner.cfg["resources"]["request_timeout_seconds"]) as r:
                        if r.status_code == 200 and "Range" in headers and not head:
                            raise RuntimeError("Upstream ignored range request; refusing full file transfer")
                        r.raise_for_status()
                        length = int(r.headers.get("Content-Length", 0))
                        if not head and not length:
                            raise RuntimeError("Unknown response length; cannot reserve budget")
                        if not head:
                            owner.ledger.reserve(length)
                            reservation = length
                        self.send_response(r.status_code)
                        # Do not accumulate an idle server thread for each
                        # successive short-lived DuckDB reader connection.
                        self.send_header('Connection', 'close')
                        self.close_connection = True
                        for key in ("Content-Length", "Content-Range", "Accept-Ranges", "Content-Type", "ETag", "Last-Modified"):
                            if key in r.headers:
                                self.send_header(key, r.headers[key])
                        self.end_headers()
                        started = True
                        if not head:
                            for chunk in r.iter_content(65536):
                                owner.ledger.add(len(chunk),owner.paths[self.path.lstrip('/').split('?')[0]])
                                received += len(chunk)
                                self.wfile.write(chunk)
                        owner.ledger.data["requests"] += 1
                except Exception as exc:
                    with owner.ledger.lock:
                        owner.ledger.data["errors"].append({"at": now(), "error": type(exc).__name__ + ": " + str(exc).split("https://")[0], "manifest_index": self.path})
                        owner.ledger.data["errors"] = owner.ledger.data["errors"][-100:]
                    if not started:
                        self.send_error(503, type(exc).__name__)
                    else:
                        self.close_connection = True
                finally:
                    with owner.ledger.lock:
                        owner.ledger.reserved -= reservation - received
                        owner.ledger.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, entry):
        return f"http://127.0.0.1:{self.server.server_port}/{self.index[entry['path']]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
