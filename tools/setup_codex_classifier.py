"""Install a checksum-verified project-local CLI; never change the global CLI."""
import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

import requests
import truststore

truststore.inject_into_ssl()
version = '0.157.0-win32-x64'
root = Path(__file__).resolve().parents[1]
response = requests.get('https://registry.npmjs.org/@openai/codex/'+version, timeout=30)
response.raise_for_status()
metadata = response.json()
if metadata['version'] != version or metadata['name'] != '@openai/codex':
    raise ValueError('Unexpected package identity')
url = metadata['dist']['tarball']
if not url.startswith('https://registry.npmjs.org/@openai/codex/'):
    raise ValueError('Unexpected artifact host/path')
archive = requests.get(url, timeout=120)
archive.raise_for_status()
expected = metadata['dist']['integrity']
observed = 'sha512-'+base64.b64encode(hashlib.sha512(archive.content).digest()).decode()
if expected != observed:
    raise ValueError('Package integrity mismatch')
target = root/'runtime'/('codex-'+version)
target.mkdir(parents=True,exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(archive.content),mode='r:gz') as tf:
    tf.extractall(target,filter='data')
executables = list(target.rglob('codex.exe'))
if len(executables)!=1:
    raise ValueError('Expected one Codex executable')
provenance = {'package':metadata['name'],'version':version,'url':url,'integrity':observed,
    'bytes':len(archive.content),'executable':str(executables[0]),'global_install_modified':False}
(root/'data/inputs/codex_classifier_runtime.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
print(json.dumps(provenance))
