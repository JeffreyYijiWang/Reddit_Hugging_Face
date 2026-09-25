"""Record limited regression and separate-case checks, not population accuracy."""
import json
import tomllib
from pathlib import Path

from reddit_reid.chatgpt_review import VERSION, EFFORT
from reddit_reid.common import load_json, now, save_json
from reddit_reid.schema import Annotation, validate_spans

root = Path('data')
reference = {d['incident_id']:d['labels']['confirmed_reidentification'] for d in load_json(root/'inputs/assistant_review_decisions.json')}
holdout = load_json(root/'inputs/chatgpt_holdout_reference.json')
reference.update({d['incident_id']:d['expected_label'] for d in holdout['cases']})
model = tomllib.loads((Path.home()/'.codex/config.toml').read_text(encoding='utf-8'))['model']
checks = []
for iid,expected in reference.items():
    bundle = load_json(root/'cases'/(iid+'.json'))
    a = load_json(root/'chatgpt_reviews'/(iid+'.json'))
    validate_spans(Annotation.model_validate(a),bundle['records'])
    assert sorted(a['review_coverage']['record_ids']) == sorted(bundle['record_ids'])
    assert a['annotation_provenance']['case_content_hash'] == bundle['content_hash']
    assert a['annotation_provenance']['version'] == VERSION
    assert a['account']['status'] == 'Unknown'
    assert not a['review_coverage']['all_thread_comments_available']
    checks.append({'incident_id':iid,'reference_label':expected,'model_label':a['confirmed_reidentification'],
        'label_agrees':expected==a['confirmed_reidentification'],'exact_evidence_validated':True})
    # The default model setting was read before and after these runs; no global
    # configuration was changed. Future runs pass the resolved name explicitly.
    a['annotation_provenance']['model_resolved'] = model
    a['annotation_provenance']['model_resolution_basis'] = 'User CLI model setting verified unchanged before and after qualification'
    save_json(root/'chatgpt_reviews'/(iid+'.json'),a,durable=False)
accepted = len(checks)==8 and all(c['label_agrees'] for c in checks)
result = {'accepted_for_model_generated_review':accepted,'evaluated_at':now(),'version':VERSION,'model':model,
    'reasoning_effort':EFFORT,'checks':checks,'calibration_cases':4,'separately_sampled_cases':4,
    'human_adjudicated':False,'population_accuracy_estimate':None,
    'limits':'Four purposive regression examples used during prompt development, plus four separately sampled negative cases reviewed by the root assistant before model outputs. This is a limited engineering qualification, not independent human validation or a recall/precision estimate. All model labels require human adjudication. Missing comments remain missing.'}
save_json(root/'inputs/chatgpt_qualification.json',result)
print(json.dumps({'accepted':accepted,'checks':len(checks),'model':model,'version':VERSION}))
if not accepted:
    raise SystemExit(1)
