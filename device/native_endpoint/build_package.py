#!/usr/bin/env python3
"""Build an explicit, checksummed daily package from pinned, supplied assets."""
import argparse,gzip,hashlib,shutil,subprocess,tarfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--assets',type=Path,required=True)
p.add_argument('--header',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();root=Path(__file__).resolve().parents[2];out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
stage=out/'runtime';model=stage/'xiaomi_neural_shadow';wake=stage/'xiaomi_native_wake_probe'
for d in (model,wake):d.mkdir(parents=True,exist_ok=True)
assets=['ld-linux-armhf.so.3','libc.so.6','libdl.so.2','libm.so.6','libonnxruntime.so','libpthread.so.0','librt.so.1','libsherpa-onnx-c-api.so','libstdc++.so.6','silero_vad_v5.onnx']
# The source asset manifest is explicitly supplied and checked, no downloads.
known={line.split()[1]:line.split()[0] for line in (a.assets/'runtime.sha256').read_text().splitlines()}
for name in assets:
 source=a.assets/name
 if hashlib.sha256(source.read_bytes()).hexdigest()!=known[name]:raise SystemExit('Asset mismatch: '+name)
 shutil.copy2(source,model/name)
src=root/'device/endpoint_probe';b=out/'build'
subprocess.run(['sh',str(src/'build_native_wake.sh'),str(b)],check=True)
subprocess.run(['sh',str(src/'build_neural_bench.sh'),str(a.header.resolve()),str(b)],check=True)
for name in ['native_wake_pool','native_resident_session']:shutil.copy2(b/name,wake/name)
shutil.copy2(b/'neural_pool',model/'neural_pool');shutil.copy2(src/'run_neural_pool.sh',model/'run_neural_pool.sh')
def manifest(folder,paths):return ''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f.relative_to(folder))+'\n' for f in sorted(paths))
(model/'runtime.sha256').write_text(manifest(model,[f for f in model.iterdir() if f.name!='runtime.sha256']))
(stage/'runtime-files.sha256').write_text(manifest(stage,[f for d in [model,wake] for f in d.iterdir()]))
with (out/'runtime.tar.gz').open('wb') as raw, gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed, tarfile.open(fileobj=compressed,mode='w') as tar:
 for f in sorted(stage.rglob('*')):
  if f.is_file():
   info=tar.gettarinfo(str(f),arcname=str(f.relative_to(stage)))
   info.mtime=0;info.uid=info.gid=0;info.uname=info.gname=''
   with f.open('rb') as data:tar.addfile(info,data)
shutil.copy2(b/'native_wake_probe.so',out/'native_asr.so')
shutil.copy2(root/'device/native_first_client.sh',out/'native_first_client.sh')
shutil.copy2(root/'device/native_endpoint/manager.sh',out/'manager.sh')
subprocess.run(['zig','cc','-target','arm-linux-gnueabihf.2.25','-Os','-Wall','-Wextra','-Werror',str(root/'device/native_endpoint/lifecycle.c'),'-o',str(out/'lifecycle')],check=True)
files=[out/n for n in ['runtime.tar.gz','native_asr.so','native_first_client.sh','manager.sh','lifecycle']]
(out/'package.sha256').write_text(manifest(out,files))
print('PACKAGE_BYTES',sum(f.stat().st_size for f in files))
print(out/'package.sha256')
