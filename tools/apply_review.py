"""Validate a restricted, explicitly authored review against complete local records."""
import json
from pathlib import Path

from reddit_reid.common import load_json, save_json, now, historical_metrics
from reddit_reid.annotate import pending_annotation
from reddit_reid.schema import Annotation, Evidence, PostProperties, validate_spans

root = Path('data')
decisions = load_json(root/'inputs/assistant_review_decisions.json')
overrides = load_json(root/'inputs/review_overrides.json', {})
for decision in decisions:
    bundle = load_json(root/'cases'/ (decision['incident_id']+'.json'))
    a = pending_annotation(bundle).model_dump()
    a.update(decision['labels'])
    a['review_status'] = 'assistant_post_review_needs_human_review'
    a['review_coverage'] = {'classification_performed':True, 'record_ids':bundle['record_ids'], 'all_retrieved_text_reviewed':True,
        'scope':'Full archived title and body of the seed submission. No comments or images collected.', 'independent_verification':False}
    a['evidence'] = []
    for e in decision['evidence']:
        row = next(r for r in bundle['records'] if r['typed_id'] == e['source_record_id'])
        start = row[e['source_field']].index(e['quote'])
        a['evidence'].append(Evidence(**e, raw_start=start, raw_end=start+len(e['quote']), thread_id=row['thread_id'], permalink=row['canonical_permalink'],
            reporting_username=row.get('author'), record_created_utc=row.get('created_utc'), role_relative_to_original_op='Seed post author; earlier original unresolved' if decision.get('original_unresolved') else 'OP',
            attribution="author's own statement").model_dump())
    if decision.get('original_unresolved'):
        a['original'] = PostProperties().model_dump()
        a['original_resolution_status'] = 'unresolved'
        a['metrics'] = historical_metrics({},[])
        a['missingness']['original_post'] = 'Referenced earlier post not identified or retrieved; seed is the report'
    for field, changes in decision.get('group_updates', {}).items():
        a[field].update(changes)
    a['annotation_provenance'] = {'method':'Codex interactive assistant review of complete supplied archived records',
        'case_content_hash':bundle['content_hash'], 'created_at':now(), 'sampling_basis':'Purposive positive/negative/insufficient-text demonstrations, not an evaluation sample',
        'automatic_model_api_used':False}
    a['missingness']['classification'] = 'Not missing; post-only assistant review, awaiting human adjudication'
    validated = validate_spans(Annotation.model_validate(a),bundle['records'])
    overrides[bundle['incident_id']] = validated.model_dump()
save_json(root/'inputs/review_overrides.json',overrides)
print(json.dumps({'validated_reviews':len(overrides)}))
