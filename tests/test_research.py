"""Synthetic fixtures only. No synthetic record is a research result."""
import json
import zipfile
from pathlib import Path

import pytest

from reddit_reid.common import typed_id, historical_metrics, digest
from reddit_reid.keywords import Matcher, normalize, normalized_offsets, import_keywords
from reddit_reid.schema import Annotation, Evidence, Actors, validate_spans, INTENTS, OUTCOMES, RELATIONSHIPS
from reddit_reid.scanner import triage_flags, select_files
from reddit_reid.cases import extract_links, group_seeds, preservation_candidates
from reddit_reid.annotate import build_batches, pending_annotation
from reddit_reid.export import HEADERS, MAPPINGS, excel_literal, text_parts


def record(rid, kind="submissions", author="synthetic_author", body="", created=100, thread=None):
    tid = typed_id(rid, "t1" if kind == "comments" else "t3")
    return {"id": rid, "typed_id": tid, "kind": kind, "thread_id": thread or tid, "author": author,
            "created_utc": created, "selftext" if kind == "submissions" else "body": body,
            "title": "Synthetic fixture", "subreddit": "synthetic_test", "canonical_permalink": "https://example.invalid/", "source": {}}


def test_typed_id_joins():
    assert typed_id("ABC") == typed_id("t3_abc") == "t3_abc"
    assert typed_id("t1_xyz", "t3") == "t1_xyz"
    with pytest.raises(ValueError):
        typed_id("abc/def")


@pytest.mark.parametrize("text", ["She RECOGNISED  my\npost", "She recognised my post", "I’ve seen Straße", "Cafe\u0301  test", "ＡＢＣ ‘it’", "  a\t b "])
def test_normalization_offset_map(text):
    value, spans = normalized_offsets(text)
    assert value == normalize(text)
    assert len(value) == len(spans)
    assert all(0 <= a < b <= len(text) for a,b in spans)


def test_raw_match_unicode_whitespace_and_boundary():
    q = [{"query_id": "q", "normalized": "recognized my post"}]
    matcher = Matcher(q)
    text = "🙂 She RECOGNISED\t my\npost yesterday."
    h = matcher.find(text)[0]
    assert text[h["start"]:h["end"]] == "RECOGNISED\t my\npost"
    assert not matcher.find("recognized my poster")


def test_title_body_boundary_does_not_match():
    matcher = Matcher([{"query_id":"q","normalized":"found my post"}])
    assert matcher.find("found my") == matcher.find("post") == []


def test_duplicate_queries_keep_origin_rows(tmp_path):
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    path = tmp_path / "queries.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="All first person searches" sheetId="1" r:id="r1"/><sheet name="General" sheetId="2" r:id="r2"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="r1" Target="worksheets/s1.xml"/><Relationship Id="r2" Target="worksheets/s2.xml"/></Relationships>')
        for n,phrase in [(1,"My friend found my post"),(2,"MY FRIEND FOUND MY POST")]:
            z.writestr(f"xl/worksheets/s{n}.xml", f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="B1" t="inlineStr"><is><t>Search Phrase</t></is></c></row><row r="2"><c r="B2" t="inlineStr"><is><t>{phrase}</t></is></c></row></sheetData></worksheet>')
    data = tmp_path / "data"; (data/"inputs").mkdir(parents=True)
    audit = import_keywords({"keyword_workbook": str(path), "data_root": str(data)})
    queries = json.loads((data/"inputs/keywords.json").read_text())
    assert audit["unique_count"] == 1 and audit["duplicate_count"] == 1
    assert len(queries[0]["origins"]) == 2
    assert audit["only_aggregate"] == audit["only_category"] == []


def test_negation_and_hypothetical_are_review_flags_not_yes_no():
    for text in ["If my partner found my post I would worry", "My partner did not find my post", "I hope nobody finds this"]:
        assert "negation_or_hypothetical_language" in triage_flags(text)
    assert "negation_or_hypothetical_language" not in triage_flags("My partner found my post yesterday")
    assert Annotation(incident_id="synthetic").confirmed_reidentification == "Unsure"


def test_reporter_finder_roles_and_stranger_distance():
    actors = Actors(reporters=["OP/author"], finders=["Subject of post"], finder_relationship_subtypes=["partner/ex-partner"])
    assert actors.reporters != actors.finders
    with pytest.raises(ValueError, match="Stranger"):
        Annotation(incident_id="s", actors=Actors(finder_relationship_subtypes=["stranger"], finder_graph_distance_observed=3))
    assert "Third-degree connection or greater / Stranger (other reddit users)" in RELATIONSHIPS


def test_evidence_offset_validation_and_quoted_attribution():
    r = record("abc", body='Quoted author: "my partner found my post"')
    phrase = "my partner found my post"; start = r["selftext"].index(phrase)
    e = Evidence(evidence_id="s", quote=phrase, raw_start=start, raw_end=start+len(phrase), source_record_id=r["typed_id"], thread_id=r["thread_id"], source_field="selftext", reporting_username=r["author"], record_created_utc=100, attribution="quoted or preserved text")
    a = Annotation(incident_id="s", evidence=[e])
    validate_spans(a,[r])
    a.evidence[0].raw_start += 1
    with pytest.raises(ValueError, match="mismatch"):
        validate_spans(a,[r])


def test_deleted_users_not_merged_and_history_strictly_prior():
    deleted = record("abc", author="[deleted]")
    assert historical_metrics(deleted,[record("def",author="[deleted]",created=1)])["observed_prior_posts_lower_bound"] is None
    op = record("abc",created=100)
    history = [record("before",created=99),record("same",created=100),record("after",created=101)]
    metrics = historical_metrics(op,history)
    assert metrics["observed_prior_posts_lower_bound"] == 1
    assert metrics["account_age_seconds"] is None
    assert metrics["weekly_visitors_at_posting"] is None
    assert metrics["upvotes"] is None
    assert metrics["observed_active_subreddits_including_target"] == 1


def test_non_op_anecdote_remains_separate_from_thread_incident():
    op = record("abc")
    c = record("xyz", "comments", "someone_else", thread="t3_abc")
    groups = group_seeds([op,c],[{"typed_id":"t3_abc"},{"typed_id":"t1_xyz"}])
    assert len(groups) == 2


def test_cross_month_comment_selection_and_target_hash():
    cfg = {"context":{"start_month":"2010-01","end_month":"2010-03"},"discovery":{"start_month":"2010-01","end_month":"2010-01"}}
    files = [{"kind":"comments","month":m,"path":m} for m in ["2010-01","2010-02","2010-03"]]
    assert len(select_files(cfg,files,"context")) == 3
    assert len(select_files(cfg,files,"discovery")) == 1
    assert digest(["t3_a"]) != digest(["t3_a","t3_b"])


def test_series_link_uncertainty_and_synthetic_update_three():
    update = record("upd3", body="My previous post: https://www.reddit.com/r/test/comments/og1/title/\nMy partner found my post.")
    links = extract_links(update)
    assert links[0]["target_thread"] == "t3_og1" and links[0]["supported"]
    bare = record("upd3", body="Read https://www.reddit.com/r/test/comments/og1/title/")
    assert not extract_links(bare)[0]["supported"]
    comment = record("com1","comments","[deleted]",body=update["selftext"],thread="t3_upd3")
    assert not extract_links(comment, "[deleted]")[0]["supported"]


def test_preservation_runs_with_accessible_text():
    op = record("abc",body="Synthetic original text. "*10)
    copy = record("com1","comments","AutoModerator",body=op["selftext"],thread="t3_abc")
    p = preservation_candidates([op,copy])[0]
    assert p["type"] == "subreddit automod in comments" and p["completeness"] == "full"


def test_full_batch_text_coverage_and_schema_groups(tmp_path):
    op = record("abc",body="Synthetic original")
    comment = record("xyz","comments",body="large comment "*6000,thread="t3_abc")
    bundle = {"incident_id":"synthetic", "original_post_id":"t3_abc", "seed_record_ids":["t1_xyz"], "records":[op,comment],
              "coverage":{},"original_resolution_status":"provisional seed thread","content_hash":"synthetic"}
    batches = build_batches(bundle,10000)
    segments = [s for b in batches for s in b["segments"] if s["record"]["typed_id"] == "t1_xyz" and s["field"] == "body"]
    assert "".join(s["text"] for s in segments) == comment["body"]
    assert all(b["original_full_record"] == op for b in batches)
    a = pending_annotation(bundle).model_dump()
    for group in ["original", "series", "evidence", "actors", "discovery", "preservation", "account", "outcomes", "metrics", "missingness"]:
        assert group in a
    assert len(INTENTS) == 10 and len(OUTCOMES) == 13
    a["synthetic_fixture_only"] = True
    (tmp_path/"synthetic.json").write_text(json.dumps(a))


def test_excel_limits_and_formula_safety():
    text = "🙂"*40000
    parts = text_parts(text)
    assert "".join(parts) == text
    assert all(len(p.encode("utf-16-le"))//2 < 32767 for p in parts)
    assert excel_literal("=HYPERLINK(\"evil\")").startswith("'")
    assert excel_literal("  @test").startswith("'")
    assert excel_literal("regular") == "regular"
    assert len(HEADERS) == len(MAPPINGS) == 42


def test_atomic_store_catalog_and_recovery(tmp_path):
    from reddit_reid.store import Store
    for folder in ['state','records/submissions','records/comments','tmp','cache']:
        (tmp_path/folder).mkdir(parents=True)
    cfg = {'data_root':str(tmp_path),'resources':{'memory_limit':'256MB','threads':1,'spill_bytes':64000000}}
    store = Store(cfg, remote=False)
    try:
        r = record('abc',body='synthetic persisted text')
        store.put_records([r])
        store.put_records([r])
        assert len(store.records()) == 1
        chunks = list((tmp_path/'records/submissions').glob('*.parquet'))
        assert len(chunks) == 1
        store.db.execute('DELETE FROM records')
        assert store.recover()['recovered_rows'] == 1
        assert store.records()[0]['selftext'] == r['selftext']
        store.checkpoint('synthetic','discovery','synthetic.parquet','partial',10,{})
        assert not store.completed('synthetic')
    finally:
        store.close()


def test_large_export_partition_has_no_dropped_or_duplicated_rows():
    from reddit_reid.export import workbook_parts
    tables = {'Summary':{'headers':['Measure','Value'],'rows':[['test','synthetic']]},
              'Review':{'headers':['id'],'rows':[[n] for n in range(7)]},
              'Posts':{'headers':['id'],'rows':[[n] for n in range(4)]}}
    parts = list(workbook_parts(tables,3))
    assert len(parts) == 3
    for name in ('Review','Posts'):
        assert [row for _,part,_ in parts for row in part[name]['rows']] == tables[name]['rows']
    assert parts[1][2]['Review'] == {'first_global_data_row':4,'last_global_data_row':6}
    assert parts[2][2]['Posts']['first_global_data_row'] is None
