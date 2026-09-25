"""Schema demonstration only; never added to case index or research database."""
from reddit_reid.common import save_json
from reddit_reid.annotate import pending_annotation
from reddit_reid.schema import Annotation, Evidence, validate_spans, INTENTS, EVIDENCE_TYPES, OUTCOMES, RELATIONSHIPS, SUBTYPES, PRESERVATION_TYPES

record = {'typed_id':'t3_synthetic', 'thread_id':'t3_synthetic', 'kind':'submissions',
          'title':'SYNTHETIC SCHEMA EXAMPLE', 'selftext':'My partner found my post.',
          'author':'synthetic_author', 'created_utc':100, 'subreddit':'synthetic_fixture',
          'canonical_permalink':'https://example.invalid/synthetic', 'source':{}}
bundle = {'incident_id':'synthetic_only', 'original_post_id':record['typed_id'],
          'seed_record_ids':[record['typed_id']], 'records':[record], 'record_ids':[record['typed_id']],
          'coverage':{'synthetic_fixture_only':True}, 'original_resolution_status':'provisional seed thread',
          'content_hash':'synthetic_not_a_research_result'}
annotation = pending_annotation(bundle).model_dump()
annotation.update(confirmed_reidentification='Yes', review_status='synthetic_demonstration_only',
                  rationale='Invented qualification example; no real event is asserted.')
annotation['evidence'] = [Evidence(evidence_id='synthetic_e1', quote=record['selftext'], raw_start=0,
    raw_end=len(record['selftext']), source_record_id=record['typed_id'], thread_id=record['thread_id'],
    source_field='selftext', reporting_username=record['author'], record_created_utc=100).model_dump()]
annotation['actors'].update(reporters=['OP/author'], finder_relationship_subtypes=['partner/ex-partner'])
annotation['preservation'] = [{'post_id':record['typed_id'], 'type':'unknown'}]
annotation['outcomes'] = [{'label':'Unclear'}]
annotation = validate_spans(Annotation.model_validate(annotation), [record]).model_dump()
save_json('data/inputs/synthetic_completeness_example.json', {'synthetic_fixture_only':True,
    'warning':'Invented schema demonstration. Excluded from every research count and case index.',
    'annotation':annotation, 'available_labels':{'intents':INTENTS, 'evidence_types':EVIDENCE_TYPES,
        'outcomes':OUTCOMES, 'relationships':RELATIONSHIPS, 'relationship_subtypes':SUBTYPES, 'preservation':PRESERVATION_TYPES}})
print('Saved separately labeled synthetic schema example.')
