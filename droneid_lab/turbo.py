"""C/C++ TurboFEC backend using proto17's exact decode parameters.

No fallback. Input is 7200 unpacked bits after descrambling; output is 176 bytes.
CRC++ CRC24 is independently cross-checked with Python crcmod.
The submitted runtime uses the supplied WASM SIMD module through Node 26.x.
"""
from pathlib import Path
from functools import lru_cache
import base64,json,os,re,shutil,subprocess
import numpy as np
import crcmod

E, D, K, OUTPUT_BYTES = 7200, 1412, 1408, 176
_crc24 = crcmod.mkCrcFun(0x1864CFB, initCrc=0, rev=False, xorOut=0)

class TurboUnavailable(RuntimeError):
    pass

class TurboBackendError(RuntimeError):
    pass

def crc24_ltea(data):
    return int(_crc24(bytes(data)))

def unpacked_bits(bits):
    a=np.asarray(bits)
    if a.ndim!=1 or a.size!=E or a.dtype.kind not in 'bui' or not np.all((a==0)|(a==1)):
        raise ValueError('Turbo cần vector 7200 bit bool/integer 0 hoặc 1; không phải ASCII/packed bytes.')
    return np.ascontiguousarray(a,dtype=np.uint8)

def validated_result(data,streams,rc,residue,backend_name):
    if rc not in (0,1):raise TurboBackendError(f'C/C++ Turbo error {rc}; output không được dùng.')
    if len(data)!=OUTPUT_BYTES or streams.shape!=(3,D):raise TurboBackendError('Sai kích thước output/streams.')
    calculated=crc24_ltea(data[:173]);received=int.from_bytes(data[173:176],'big')
    if crc24_ltea(data)!=residue or (rc==0)!=(received==calculated) or (rc==0)!=(residue==0):
        raise TurboBackendError('CRC24 C++/Python không khớp; không chấp nhận output.')
    return {'bytes':data,'input_bits':E,'output_bytes':len(data),'rate_unmatched':streams,
            'parity_used':True,'crc24_checked':True,'crc24':rc==0,
            'crc24_received':f'{received:06x}','crc24_calculated':f'{calculated:06x}',
            'crc24_residue':f'{residue:06x}','iterations':4,
            'backend':backend_name,'native_returncode':rc}

class WasmBackend:
    """Explicit production backend: same C/C++, compiled to WASM SIMD, run by Node."""
    def __init__(self,node=None,worker=None):
        self.node=node or os.environ.get('DRONEID_NODE') or shutil.which('node')
        self.worker=Path(worker) if worker else Path(__file__).parent/'native/turbo_worker.cjs'
        if not self.node or not Path(self.node).is_file():
            raise TurboUnavailable('Không tìm thấy Node. Cài Node.js 26.x từ nodejs.org, mở lại terminal/app; hoặc đặt DRONEID_NODE tới node.exe. Không tự chuyển sang baseline.')
        required=[self.worker,self.worker.with_name('droneid_turbo.wasm')]
        if not all(p.is_file() for p in required):
            raise TurboUnavailable('Thiếu backend Turbo. Giải nén lại đủ thư mục droneid_lab/native (turbo_worker.cjs và droneid_turbo.wasm). Không cần biên dịch và không fallback.')
        try:
            version=subprocess.run([self.node,'--version'],capture_output=True,text=True,timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise TurboUnavailable('Không chạy được Node. Kiểm tra cài đặt Node.js 26.x; không tự đổi chính sách Windows.') from exc
        match=re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)',version.stdout.strip())
        if version.returncode or not match or int(match[1])!=26:
            raise TurboUnavailable('Bản nộp yêu cầu Node.js 26.x; phiên bản đã kiểm là 26.13.1. Kiểm tra node --version.')
        self.version=version.stdout.strip()
        probe=self.request('probe',b'')
        if probe.get('abi')!=1:raise TurboBackendError('Backend Turbo không đúng ABI 1; giải nén lại bản nộp.')

    def request(self,operation,data):
        request=json.dumps({'op':operation,'data':base64.b64encode(data).decode('ascii')}).encode('ascii')
        try:
            p=subprocess.run([self.node,'--disable-warning=ExperimentalWarning',str(self.worker)],input=request,capture_output=True,timeout=20,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise TurboUnavailable(f'Turbo WASM runtime lỗi {type(exc).__name__}; không fallback.') from exc
        if p.returncode:raise TurboBackendError(f'Turbo WASM worker exit {p.returncode}. Kiểm tra Node.js 26.x và giải nén lại backend; không có output hợp lệ.')
        try:return json.loads(p.stdout)
        except (ValueError,UnicodeError) as exc:raise TurboBackendError('Turbo worker trả dữ liệu sai giao thức.') from exc

    def decode(self,bits):
        incoming=unpacked_bits(bits)
        r=self.request('decode',incoming.tobytes())
        if r['rc'] not in (0,1):raise TurboBackendError(f'C/C++ Turbo error {r["rc"]}; không dùng output.')
        data=base64.b64decode(r['output'],validate=True)
        streams=np.frombuffer(base64.b64decode(r['streams'],validate=True),dtype=np.int8).copy().reshape(3,D)
        return validated_result(data,streams,r['rc'],r['residue'],'proto17/TurboFEC C++ WASM SIMD / Node')

@lru_cache(maxsize=1)
def backend():
    # Deliberately selected, visible backend; no attempt to silently fall back.
    return WasmBackend()

def turbo_decode(bits):
    return backend().decode(bits)
