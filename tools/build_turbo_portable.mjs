// Build compiler AND decoder as WebAssembly; no native compiler executable needed.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createToolchain,CLANG_DRIVER_DEFAULT_ARGS} from '../native_turbo/.wasm_compiler/node_modules/@live-codes/clang-wasm/src/toolchain.node.js';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const n=path.join(root,'native_turbo'), out=path.join(root,'droneid_lab/native');
const evidence=path.join(root,'evidence/turbo_20261118');
fs.mkdirSync(evidence,{recursive:true});
const sourceManifest=JSON.parse(fs.readFileSync(path.join(n,'source_manifest.json')));
for(const [rel,expected] of Object.entries(sourceManifest.files)){
 const actual=crypto.createHash('sha256').update(fs.readFileSync(path.join(n,rel))).digest('hex');
 if(actual!==expected)throw Error('Source differs from pinned manifest: '+rel);
}
const t=await createToolchain(); const r=t.runtime; const commands=[];
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
function mount(host,guest){for(const e of fs.readdirSync(host,{withFileTypes:true})){
  if(e.isDirectory())mount(path.join(host,e.name),guest+'/'+e.name);
  else if(e.name.endsWith('.h'))t.addFile(guest+'/'+e.name,fs.readFileSync(path.join(host,e.name)));
}}
mount(path.join(n,'third_party/turbofec/include'),'include');
mount(path.join(n,'third_party/CRCpp/inc'),'crc');
mount(path.join(n,'third_party/turbofec/src'),'src');
const result=await t.captureCompilerOutput(async()=>{
  const objects=[];
  for(const name of ['turbo_dec','turbo_enc','turbo_rate_match','remove_turbo_reference','turbo_bridge']){
    const c=name.startsWith('turbo_')&&name!=='turbo_bridge';
    const p=c?path.join(n,'third_party/turbofec/src',name+'.c'):path.join(n,'src',name+'.cc');
    const input='src/'+name+(c?'.c':'.cc'),obj='src/'+name+'.o';
    const args=[...CLANG_DRIVER_DEFAULT_ARGS,'-DHAVE_SSE3','-I/include','-I/crc','-I/src'];
    commands.push({input,source_sha256:sha(fs.readFileSync(p)),language:c?'C':'CPP',compileArgs:args,opt:'2'});
    await r.compile({input,code:fs.readFileSync(p,'utf8'),obj,language:c?'C':'CPP',compileArgs:args,opt:'2'});
    if(c)objects.push(obj);
  }
  const reference='remove_turbo_reference.wasm';
  await r.link([...objects,'src/remove_turbo_reference.o'],reference,'none','CPP');
  fs.mkdirSync(path.join(n,'build_wasm'),{recursive:true});
  fs.writeFileSync(path.join(n,'build_wasm',reference),r.memfs.getFileContents(reference));
  const exports=['droneid_turbo_decode','droneid_turbo_abi_version','droneid_test_decode_streams','droneid_test_encode','malloc','free'];
  const lib='lib/wasm32-wasi',dest='droneid_turbo.wasm';
  const args=['wasm-ld','--no-entry','--export=__wasm_call_ctors',...exports.map(x=>'--export='+x),'-z','stack-size=1048576',
    '-L'+lib+'/noeh','-L'+lib,...objects,'src/turbo_bridge.o','-lc++','-lc++abi','-lc','-lm',
    '-L'+r.compilerConfig.compilerRuntimeLibDir,'-lclang_rt.builtins-wasm32','-o',dest];
  commands.push({link:args});
  await r.run(await r.getModule(r.assetUrls.lld),r.log,...args);
  fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,dest),r.memfs.getFileContents(dest));
});
fs.writeFileSync(path.join(evidence,'build_portable.log'),result.raw+(result.error?'\n'+result.error.stack:''));
if(result.error)throw result.error;
const manifest={backend:'TurboFEC C/C++ WASM SIMD; Clang compiler also hosted in WASM',node:process.version,
  compiler:r.compilerConfig,commands,package_lock_sha256:sha(fs.readFileSync(path.join(n,'.wasm_compiler/package-lock.json'))),
  source_commits:sourceManifest.repositories,
  files:Object.fromEntries([path.join(out,'droneid_turbo.wasm'),path.join(n,'build_wasm/remove_turbo_reference.wasm')].map(p=>[path.relative(root,p),sha(fs.readFileSync(p))]))};
fs.writeFileSync(path.join(n,'portable_build_manifest.json'),JSON.stringify(manifest,null,2));
console.log(JSON.stringify(manifest,null,2));t.dispose();
