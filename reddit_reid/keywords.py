from __future__ import annotations

import collections
import re
import shutil
import unicodedata
import zipfile
import functools
from pathlib import Path
from xml.etree import ElementTree as ET

import ahocorasick

from .common import digest, save_json

VERSION = "nfkc-casefold-space-apostrophe-recognise-v1"
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "＇": "'"})
SPELLINGS = {"recognised": "recognized", "recognise": "recognize", "recognises": "recognizes", "recognising": "recognizing", "realised": "realized", "realise": "realize"}
SPELL_RE = re.compile(r"\b(" + "|".join(SPELLINGS) + r")\b")


def rough_normalize(text):
    return text.lower() if text.isascii() else unicodedata.normalize("NFKC", text).casefold()


def normalize(text):
    text = rough_normalize(text)
    if any(c in text for c in "’‘ʼ＇"):
        text = text.translate(APOSTROPHES)
    text = " ".join(text.split())
    return SPELL_RE.sub(lambda m: SPELLINGS[m.group()], text) if "recogni" in text or "reali" in text else text


def normalized_offsets(text):
    # Normalize base characters together with combining marks to preserve NFKC.
    chars, spans = [], []
    for m in re.finditer(r"[^\u0300-\u036f][\u0300-\u036f]*|[\u0300-\u036f]+", text):
        for char in unicodedata.normalize("NFKC", m.group()).casefold().translate(APOSTROPHES):
            if char.isspace():
                if chars and chars[-1] == " ":
                    spans[-1] = (spans[-1][0], m.end())
                    continue
                char = " "
            chars.append(char)
            spans.append((m.start(), m.end()))
    if chars and chars[-1] == " ":
        chars.pop(); spans.pop()
    if chars and chars[0] == " ":
        chars.pop(0); spans.pop(0)
    value = "".join(chars)
    for m in reversed(list(SPELL_RE.finditer(value))):
        replacement = SPELLINGS[m.group()]
        new_spans = [spans[m.start()+i] for i in range(len(replacement))]
        value = value[:m.start()] + replacement + value[m.end():]
        spans[m.start():m.end()] = new_spans
    assert value == normalize(text), "Normalization offset map mismatch"
    return value, spans


def workbook_rows(path):
    """Read OOXML without executing formulas or following external relationships."""
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = ["".join(si.itertext()) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        rels = {e.attrib["Id"]: e.attrib["Target"] for e in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).find("s:sheets", ns):
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = rels[rid]
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            rows = []
            for row in ET.fromstring(z.read(target)).findall(".//s:sheetData/s:row", ns):
                values = {}
                for c in row:
                    col = re.match(r"[A-Z]+", c.attrib["r"]).group()
                    v = c.find("s:v", ns)
                    if c.find("s:f", ns) is not None:
                        value = None  # never silently use stale formula caches for queries
                    elif c.attrib.get("t") == "s" and v is not None:
                        value = shared[int(v.text)]
                    elif c.attrib.get("t") == "inlineStr":
                        value = "".join(c.find("s:is", ns).itertext())
                    else:
                        value = v.text if v is not None else None
                    values[col] = value
                rows.append((int(row.attrib["r"]), values))
            yield sheet.attrib["name"], rows


def import_keywords(cfg):
    path = Path(cfg["keyword_workbook"])
    queries, counts, all_origins = {}, {}, []
    for sheet, rows in workbook_rows(path):
        header = next(((i, vals) for i, vals in rows if "Search Phrase" in vals.values()), None)
        if not header:
            counts[sheet] = {"error": "Search Phrase header missing"}
            continue
        header_row, headers = header
        phrase_col = next(k for k, v in headers.items() if v == "Search Phrase")
        count = 0
        for row, vals in rows:
            phrase = vals.get(phrase_col)
            if row <= header_row or not phrase or not phrase.strip():
                continue
            normalized = normalize(phrase)
            if not normalized:
                continue
            provenance = {"file": path.name, "sheet": sheet, "row": row, "phrase": phrase,
                          "metadata": {name: vals.get(col) for col, name in headers.items() if name and name != "Search Phrase"}}
            query = queries.setdefault(normalized, {"query_id": "q_" + digest(normalized)[:16], "normalized": normalized, "origins": []})
            query["origins"].append(provenance)
            all_origins.append(provenance)
            count += 1
        counts[sheet] = {"nonempty_phrases": count}
    ordered = sorted(queries.values(), key=lambda q: q["query_id"])
    aggregate = {q["normalized"] for q in ordered if any(o["sheet"] == "All first person searches" for o in q["origins"])}
    categories = {q["normalized"] for q in ordered if any(o["sheet"] != "All first person searches" for o in q["origins"])}
    close_groups = collections.defaultdict(list)
    for q in ordered:
        close_groups[re.sub(r"[^a-z0-9]", "", q["normalized"])].append(q["query_id"])
    audit = {"filename": path.name, "sha256": digest(path.read_bytes()), "normalization": VERSION,
             "original_count": len(all_origins), "unique_count": len(ordered), "duplicate_count": len(all_origins) - len(ordered),
             "new_query_count": 0, "supplementary_queries": 0, "sheets": counts,
             "only_aggregate": sorted(aggregate - categories), "only_category": sorted(categories - aggregate),
             "close_variant_groups_for_review": [v for v in close_groups.values() if len(v) > 1],
             "filename_note": "User explicitly identified the workbook in the folder; filename does not establish identity with the prompt's (4) version.",
             "query_set_hash": digest(ordered)}
    root = Path(cfg["data_root"]) / "inputs"
    shutil.copy2(path, root / path.name)
    save_json(root / "keywords.json", ordered)
    save_json(root / "keyword_audit.json", audit)
    return audit


class Matcher:
    def __init__(self, queries):
        self.automaton = ahocorasick.Automaton()
        for q in queries:
            self.automaton.add_word(q["normalized"], (q["query_id"], q["normalized"]))
        if queries:
            self.automaton.make_automaton()
        self.empty = not queries
        self.anchor_automaton = ahocorasick.Automaton()
        self.anchor_words = set()
        # Every query contributes a required normalized word. This only avoids
        # expensive normalization on texts that cannot possibly match; it does
        # not add, remove or replace any discovery query.
        preferred = "stumbled traced exposed doxxed knows found across saw sent lurks recognized realized identified linked".split()
        self.prefilter_enabled = True
        for q in queries:
            words = __import__('re').findall(r"[a-z]{3,}", q["normalized"])
            word = next((w for w in preferred if w in words), max(words, key=len) if words else None)
            if not word:
                self.prefilter_enabled = False
                break
            self.anchor_automaton.add_word(word, word)
            self.anchor_words.add(word)
            # British spellings precede spelling normalization at this stage.
            for variant, canonical in SPELLINGS.items():
                if word == canonical:
                    self.anchor_automaton.add_word(variant, variant)
                    self.anchor_words.add(variant)
        if self.prefilter_enabled and queries:
            self.anchor_automaton.make_automaton()

    def coarse_pattern(self):
        if not self.prefilter_enabled:
            return None
        return '(?:' + '|'.join(sorted(self.anchor_words)) + '|' + ascii_compatibility_class() + ')'

    def find(self, text):
        if not text or self.empty:
            return []
        if self.prefilter_enabled and next(self.anchor_automaton.iter(rough_normalize(text)), None) is None:
            return []
        norm = normalize(text)
        found = list(self.automaton.iter(norm))
        if not found:
            return []
        _, mapping = normalized_offsets(text)
        result = []
        for end, (qid, phrase) in found:
            start = end - len(phrase) + 1
            # Word boundaries prevent e.g. 'my post' matching 'my poster'.
            if (start and norm[start-1].isalnum() and phrase[0].isalnum()) or (end+1 < len(norm) and norm[end+1].isalnum() and phrase[-1].isalnum()):
                continue
            raw_start, raw_end = mapping[start][0], mapping[end][1]
            result.append({"query_id": qid, "start": raw_start, "end": raw_end, "quote": text[raw_start:raw_end],
                           "context": text[max(0, raw_start-120):raw_end+120]})
        return result


@functools.lru_cache(maxsize=1)
def ascii_compatibility_class():
    """Conservative Unicode escape hatch for a native required-word filter.

    If NFKC+casefold can introduce an ASCII letter absent from the raw text,
    at least one such character is present. Keep every text containing one.
    Punctuation/emoji need not force a full Python match by themselves.
    """
    points = [n for n in range(128,0x110000)
              if any('a' <= c <= 'z' for c in unicodedata.normalize('NFKC',chr(n)).casefold())]
    ranges = []
    start = end = points[0]
    for point in points[1:]:
        if point == end+1:
            end = point
        else:
            ranges.append((start,end)); start=end=point
    ranges.append((start,end))
    return '[' + ''.join('\\x{'+format(a,'x')+'}' + ('-\\x{'+format(b,'x')+'}' if b!=a else '') for a,b in ranges) + ']'
