import pytest

from reddit_reid.chatgpt_review import Decision, convert, input_case, strict_schema, Batch
from reddit_reid.export import annotation_sort


def example():
    record = {'typed_id':'t3_synthetic','thread_id':'t3_synthetic','kind':'submissions',
        'title':'Synthetic fixture','selftext':'My coworker recognized me from my anonymous post.',
        'author':'synthetic_author','created_utc':100,'canonical_permalink':'https://example.invalid/synthetic','subreddit':'synthetic'}
    bundle = {'incident_id':'synthetic','seed_record_ids':['t3_synthetic'],'records':[record],
        'record_ids':['t3_synthetic'],'original_post_id':'t3_synthetic','original_resolution_status':'provisional seed thread',
        'coverage':{'retrieved_comments':0,'comments_missing_reason':'outside_archive_coverage'},'content_hash':'synthetic'}
    decision = dict(incident_id='synthetic',reviewed_record_ids=['t3_synthetic'],label='Yes',rationale='Synthetic report of recognition.',
        earlier_original_missing=False,intent='Unclear',secondary_intents=[],evidence=[dict(record_id='t3_synthetic',field='selftext',
        quote=record['selftext'],supports=['qualification'],content_type='Other',role_relative_to_original_op='OP',
        attribution="author's own statement",event_time_expression=None)],evidence_basis=['OP self-report'],
        identity_connection_type=['author recognized'],voluntary_disclosure=None,reporters=['Unclear'],finders=['Unclear'],
        relationship='Unclear',relationship_subtypes=['unclear'],target_is_containing_thread_op=None,discovery_paths=[],
        discovery_platforms=[],found_time_expression=None,discovery_notes=None,series_status='Unclear',series_supported_total=None,
        series_count_prior_to_reidentification=None,series_basis=None,account_type='Unclear',declared_throwaway=None,
        declared_one_time_use=None,observed_account_reuse=None,outcomes=[],no_outcome_reported=True,
        explicitly_no_repercussions=None,preservation=[],additional_incident_notes=[])
    return bundle,Decision.model_validate(decision)


def test_full_source_and_missing_comments_are_preserved():
    bundle,d = example()
    assert input_case(bundle)['records'][0]['selftext'] == bundle['records'][0]['selftext']
    a = convert(d,bundle,{'method':'synthetic test only'})
    assert a['evidence'][0]['reporting_username'] == 'synthetic_author'
    assert a['evidence'][0]['raw_end'] == len(bundle['records'][0]['selftext'])
    assert a['missingness']['comments'] == 'outside_archive_coverage'
    assert a['review_coverage']['all_thread_comments_available'] is False
    assert a['account']['status'] == 'Unknown'


def test_hallucinated_quotes_and_unsupported_groups_are_rejected():
    bundle,d = example()
    d.evidence[0].quote = 'Invented identification proof'
    with pytest.raises(ValueError,match='exact substring'):
        convert(d,bundle,{})


def test_unknown_preservation_does_not_require_a_fabricated_quote():
    from reddit_reid.chatgpt_review import PreservationDecision
    bundle,d = example()
    d.preservation = [PreservationDecision(post_id='t3_synthetic',type='unknown',source_record_id=None,
        source_url=None,completeness='unknown',evidence_indexes=[])]
    assert convert(d,bundle,{})['preservation'][0]['type'] == 'unknown'
    bundle,d = example()
    d.series_status = 'One-off'
    with pytest.raises(ValueError,match='series'):
        convert(d,bundle,{})
    bundle,d = example()
    d.reviewed_record_ids = []
    with pytest.raises(ValueError,match='cover'):
        convert(d,bundle,{})


def test_yes_no_unsure_pending_sort_and_strict_schema():
    rows = [{'incident_id':str(i),'confirmed_reidentification':label,'review_status':status}
        for i,(label,status) in enumerate([('Unsure','pending'),('Unsure','reviewed'),('No','reviewed'),('Yes','reviewed')])]
    assert [r['incident_id'] for r in sorted(rows,key=annotation_sort)] == ['3','2','1','0']
    schema = strict_schema(Batch.model_json_schema())
    decision = schema['$defs']['Decision']
    assert decision['additionalProperties'] is False
    assert set(decision['required']) == set(decision['properties'])
