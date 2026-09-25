"""Pinned upstream binaries/model, verified before local inference."""
import hashlib
import zipfile
from pathlib import Path
import requests
import truststore
from reddit_reid.common import save_json, now

truststore.inject_into_ssl()
assets = [
 ('runtime/llama.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11177/llama-b11177-bin-win-cuda-12.4-x64.zip','14e756ba453e29db57578c1e5791245fe05c893671d3b334e08482ba1a0946bb'),
 ('runtime/cudart.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11177/cudart-llama-bin-win-cuda-12.4-x64.zip','8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6'),
 ('models/Qwen3-4B-Q4_K_M.gguf','https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf','7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'),
]
verified = []
for name,url,expected in assets:
    path = Path(name); path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        partial = path.with_suffix(path.suffix+'.partial')
        with requests.get(url,stream=True,timeout=(30,120)) as response:
            response.raise_for_status()
            with partial.open('wb') as out:
                for chunk in response.iter_content(1024*1024): out.write(chunk)
        partial.replace(path)
    with path.open('rb') as f: actual = hashlib.file_digest(f,'sha256').hexdigest()
    if actual != expected: raise ValueError('Checksum mismatch: '+name)
    if path.suffix == '.zip':
        target=Path('runtime/llama').resolve(); target.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path) as z:
            for member in z.namelist():
                if not (target/member).resolve().is_relative_to(target): raise ValueError('Unsafe ZIP path')
            z.extractall(target)
    verified.append({'path':str(path.resolve()),'url':url,'sha256':actual,'bytes':path.stat().st_size})
    print('Verified '+name,flush=True)
save_json('data/inputs/local_classifier_provenance.json',{'verified_at':now(),'assets':verified,
    'model':'Qwen3-4B Q4_K_M','runtime':'llama.cpp b11177','purpose':'Local annotation, no tools or independent account lookup',
    'traffic_basis':'Setup downloads, separate from archive-query budget'})
