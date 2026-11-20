// Local stdin/stdout adapter. No dataset/network access or payload logging.
const fs=require('node:fs');
const path=require('node:path');
const {WASI}=require('node:wasi');
(async()=>{
 const request=JSON.parse(fs.readFileSync(0,'utf8'));
 const wasi=new WASI({version:'preview1',args:[],env:{},preopens:{},returnOnExit:true});
 const module=await WebAssembly.compile(fs.readFileSync(path.join(__dirname,'droneid_turbo.wasm')));
 const instance=await WebAssembly.instantiate(module,wasi.getImportObject());
 wasi.initialize(instance);const m=instance.exports;m.__wasm_call_ctors();
 if(m.droneid_turbo_abi_version()!==1)throw Error('Turbo ABI mismatch');
 if(request.op==='probe'){
  process.stdout.write(JSON.stringify({abi:m.droneid_turbo_abi_version(),node:process.version}));return;
 }
 const data=Buffer.from(request.data,'base64');
 const incoming=m.malloc(Math.max(data.length,1)),output=m.malloc(7200),crc=m.malloc(4),streams=m.malloc(4236);
 try {
  new Uint8Array(m.memory.buffer).set(data,incoming);
  const bytes=(p,n)=>Buffer.from(new Uint8Array(m.memory.buffer,p,n)).toString('base64');
  let response;
  if(request.op==='decode'){
   const rc=m.droneid_turbo_decode(incoming,data.length,output,176,crc,streams);
   response={rc};if(rc===0||rc===1)Object.assign(response,{output:bytes(output,176),streams:bytes(streams,4236),residue:new DataView(m.memory.buffer).getUint32(crc,true)});
  } else if(request.op==='test_encode'){
   const rc=m.droneid_test_encode(incoming,data.length,output);response={rc};if(rc===0)response.output=bytes(output,7200);
  } else if(request.op==='test_decode_streams'){
   if(data.length!==4236)throw Error('Bad test stream size');
   const rc=m.droneid_test_decode_streams(incoming,output);response={rc};if(rc===0)response.output=bytes(output,176);
  } else throw Error('Unknown Turbo operation');
  process.stdout.write(JSON.stringify(response));
 }finally{for(const p of [incoming,output,crc,streams])m.free(p);}
})().catch(e=>{process.stderr.write('Turbo worker: '+e.message+'\n');process.exitCode=2;});
