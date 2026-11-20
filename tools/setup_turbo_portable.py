"""Install the pinned WASM-hosted build tools locally, without Python/DSP changes.

Source checkout requires native_turbo/third_party and its source_manifest.json.
The release source bundle contains these small source trees, excluding .git.
"""
from pathlib import Path
import sys,subprocess,shutil,json,hashlib
root=Path(__file__).resolve().parents[1];n=root/'native_turbo'
manifest=json.loads((n/'source_manifest.json').read_text())
for rel,expected in manifest['files'].items():
    if hashlib.sha256((n/rel).read_bytes()).hexdigest()!=expected:raise RuntimeError('Source hash mismatch: '+rel)
npm=shutil.which('npm.cmd') or shutil.which('npm')
if not npm:raise RuntimeError('Install Node separately; tested Node v26.13.1. No DSP packages needed.')
destination=n/'.wasm_compiler';destination.mkdir(exist_ok=True)
for name in ['package.json','package-lock.json']:
    shutil.copyfile(n/'toolchain'/name,destination/name)
command=[npm,'ci','--prefix',str(destination),'--ignore-scripts','--no-audit','--no-fund']
subprocess.run(command,check=True)
print('Toolchain ready. Next: node tools/build_turbo_portable.mjs')
