"""Shared, explicit stages. Baseline mode retains reference decisions; experimental modes are opt-in."""
from dataclasses import dataclass, asdict, field
from pathlib import Path
import contextlib, csv, io, json, math, threading
import numpy as np
from .vendor.SpectrumCapture import SpectrumCapture
from .vendor.Packet import Packet
from .vendor.qpsk import Decoder, rm_turbo_rx
from .vendor.goldgen import gold
from .vendor.droneid_packet import DroneIDPacket
from .vendor import helpers
import bitarray

LOCK=threading.RLock()  # reference payload class has shared dictionary; serialize library calls

@contextlib.contextmanager
def quiet():
    with LOCK, contextlib.redirect_stdout(io.StringIO()):
        yield

@dataclass
class Config:
    fs: float=50_000_000
    fc: float|None=None
    format: str='float32'
    byte_order: str='little'
    iq_order: str='IQ'
    chunk_seconds: float=.5
    boundary: str='baseline'  # overlap uses ownership by cut midpoint
    mode: str='baseline'  # baseline, continue_crc, equalized, turbo
    equalization: str|None=None  # independent of FEC; explicit 'none' reproduces raw FFT
    def __post_init__(self):
        if self.equalization is None:
            self.equalization='zf' if self.mode in ('turbo','equalized') else 'none'
    def validate(self):
        if not math.isfinite(self.fs) or not 15.26e6 <= self.fs <= 200e6: raise ValueError('Fs phải trong [15.26, 200] MS/s cho implementation này.')
        if self.fc is not None and (not math.isfinite(self.fc) or self.fc<=0): raise ValueError('Fc phải dương hoặc để trống (unknown).')
        if self.format not in ('float32','int16') or self.byte_order not in ('little','big') or self.iq_order not in ('IQ','QI'): raise ValueError('Format/byte order/IQ order không hợp lệ.')
        if not math.isfinite(self.chunk_seconds) or not .003<=self.chunk_seconds<=.5: raise ValueError('Chunk từ 0.003 đến 0.5 giây.')
        if self.boundary not in ('baseline','overlap') or self.mode not in ('baseline','continue_crc','equalized','turbo'): raise ValueError('Chế độ không hợp lệ.')
        if self.equalization not in ('none','zf'):raise ValueError('Cân bằng kênh phải là none hoặc zf.')

class Cancelled(Exception): pass
def check_cancel(cancel):
    if cancel is not None and cancel.is_set(): raise Cancelled('Đã hủy; kết quả có thể chưa đủ file.')

class IQFile:
    """Read chunks from memmap; int16 /32768, I then Q or explicit swap."""
    def __init__(self,path,config):
        config.validate(); self.path=Path(path); self.config=config
        item=4 if config.format=='float32' else 2
        size=self.path.stat().st_size
        if size==0 or size%(2*item): raise ValueError('File rỗng hoặc số byte không chia hết cho một cặp I/Q.')
        self.count=size//(2*item)
        if self.count<max(2048,int(.001*config.fs)): raise ValueError('Dữ liệu quá ngắn: cần ít nhất 1 ms và 2048 mẫu.')
        dtype=('<' if config.byte_order=='little' else '>')+('f4' if item==4 else 'i2')
        self.raw=np.memmap(self.path,mode='r',dtype=dtype)
    def read(self,start=0,end=None):
        end=self.count if end is None else min(end,self.count)
        if not 0<=start<=end: raise ValueError('Khoảng đọc không hợp lệ.')
        pairs=self.raw[2*start:2*end].astype(np.float32).reshape(-1,2)
        if self.config.format=='int16': pairs/=32768.0
        if self.config.iq_order=='QI': pairs=pairs[:,::-1].copy()
        result=pairs.reshape(-1).view(np.complex64)
        if not np.isfinite(result).all(): raise ValueError('IQ chứa NaN/Inf.')
        return result

@dataclass
class Candidate:
    index: int
    start: int
    end: int
    fs: float
    iq: np.ndarray=field(repr=False)
    chunk: int=0

def detect(iq,fs,file_offset=0,chunk=0):
    """Exact reference detection; padded slice inferred only from validated shared memory."""
    if len(iq)<2048: return []
    if iq.dtype!=np.complex64 or iq.ndim!=1 or iq.strides!=(8,): raise ValueError('Detector cần vector complex64 contiguous.')
    with quiet(): cap=SpectrumCapture(iq,Fs=fs,skip_detection=False,debug=False,legacy=False)
    out=[]
    for p in cap.packets:
        delta=p.ctypes.data-iq.ctypes.data
        if not np.shares_memory(p,iq) or p.dtype!=iq.dtype or p.strides!=(8,) or delta<0 or delta%8: raise ValueError('Không ánh xạ được view candidate.')
        start=delta//8; end=start+len(p)
        if end>len(iq) or not np.array_equal(p,iq[start:end]): raise ValueError('Candidate view vượt biên/khác dữ liệu.')
        out.append(Candidate(len(out),start+file_offset,end+file_offset,fs,p.copy(),chunk))
    return out

def prepare(candidate):
    """Coarse offset then reference linear interpolation resampling, both arrays retained."""
    with quiet():
        offset,ok=helpers.estimate_offset(candidate.iq,candidate.fs)
        if not ok: raise ValueError('Không tìm được dải 8–11 MHz để ước lượng offset.')
        shifted=helpers.fshift(candidate.iq,-offset,candidate.fs)
        out=helpers.resample(shifted,candidate.fs,15.36e6) if candidate.fs>15.46e6 else shifted.copy()
    return {'coarse_estimate_Hz':float(offset),'applied_shift_Hz':float(-offset),'shifted':shifted,'resampled':out,'fs':15.36e6}

def synchronize(prepared):
    with quiet(): packet=Packet(prepared['resampled'].copy(),debug=False,enable_zc_detection=False,legacy=False)
    return packet

def symbols(packet,mode='baseline',equalization=None):
    if equalization is None:equalization='zf' if mode in ('turbo','equalized') else 'none'
    if equalization not in ('none','zf'):raise ValueError('Cân bằng kênh không hợp lệ.')
    with quiet():
        raw=packet.get_symbol_data(skip_zc=True)
        # Estimate the channel from the SAME FFT settings used for the data symbols.
        with_cp,full=packet.raw_data_to_symbols(packet.raw_samples_orig,packet.start,ffo=packet.detected_ffo,sampling_offset=packet.sampling_offset,linear_rotation=0)
        from .vendor.zcsequence import zcsequence_t
        # proto17 create_zc maps this 601-element sequence directly to carriers.
        # It is NOT the FFT of a 601-sample waveform (zcsequence_f).
        # Match proto17 process_file: estimate from the first ZC, no complex averaging.
        expected=zcsequence_t(600,601)
        active=np.arange(601)!=300
        channel=np.ones(601,dtype=np.complex128)
        channel[active]=full[3][active]/expected[active]
        if equalization=='zf' and (not np.isfinite(channel[active]).all() or np.any(np.abs(channel[active])<1e-12)):
            raise ValueError('Ước lượng kênh không hữu hạn hoặc gần zero; không tự chuyển sang raw FFT.')
        # DC has no transmitted reference: retain it untouched; descramble removes it.
        equalized=np.asarray(raw,dtype=np.complex128).copy()
        with np.errstate(divide='ignore',invalid='ignore'):
            equalized[:,active]/=channel[active]
    return {'raw_fft':np.asarray(raw),'channel':channel,'equalized':equalized,
            'time_with_cp':with_cp,'full_fft':np.asarray(full),
            'qpsk_input':equalized if equalization=='zf' else np.asarray(raw),
            'equalization':equalization,'channel_zc_symbol':3,'channel_zc_root':600,
            'cp_lengths':list(helpers.CP_LENGTHS),'NFFT':1024,'selected_bins':601}

def decide(input_symbols,phase=0):
    d=Decoder(list(input_symbols)); d.raw_data_to_symbol_bits(phase)
    return np.array(d.sym_bits)

def descramble(labels):
    """Factored from qpsk.Decoder.magic, preserving order and first-symbol handling."""
    labels_no_dc=np.delete(labels,300,1)
    bits=np.repeat(labels_no_dc,2,axis=1)
    bits &= np.tile([1,2],600)
    bits=bits>0
    coded=np.concatenate(bits[1:] if bits.size>7200 else bits)
    descrambled=gold(1600,len(coded),0x12345678)^coded
    return {'bits_with_first_symbol':bits,'coded_bits':coded,'descrambled':descrambled}

def systematic_decode(descrambled):
    cyclic=np.concatenate((descrambled,descrambled)).astype(int)
    systematic=cyclic[4148:4148+1412]
    if len(systematic)!=1412: raise ValueError('Không đủ systematic stream 1412 bit.')
    bits=rm_turbo_rx(systematic)
    data=bitarray.bitarray(list(bits),endian='big').tobytes()
    return {'cyclic':cyclic,'systematic':systematic,'unmatched':bits,'bytes':data,'parity_used':False,'crc24_checked':False}

def parse_payload(data):
    with LOCK:
        p=DroneIDPacket(data)
        return dict(p.droneid),bool(p.check_crc())


def decode_fec(descrambled, mode='baseline'):
    """One explicit FEC choice; backend failures never fall back to systematic."""
    if mode == 'turbo':
        from .turbo import turbo_decode
        return turbo_decode(descrambled)
    return systematic_decode(descrambled)


def confirmed(result):
    """Integrity checks, not authentication or ground truth of position."""
    return result['crc16'] is True and (result.get('decoder_mode') != 'turbo' or result['crc24'] is True)

FIELD_SCHEMA={
    'pkt_len':'byte; raw uint8, không dùng thay cho giới hạn 91 byte của parser',
    'unk':'raw uint8; ý nghĩa chưa xác minh', 'version':'raw uint8; phiên bản payload theo parser',
    'sequence_number':'raw uint16; số thứ tự', 'device_type':'text từ bảng mã uint8 kế thừa, không chứng minh hỗ trợ mọi loại trong bảng',
    'uuid_len':'byte; raw uint8', 'uuid':'text / định danh theo struct 20s',
    'serial_number':'text / nhận dạng; DroneIDPacket struct field 5',
    'latitude':'degree; raw/174533, reverse-engineered', 'longitude':'degree; raw/174533, reverse-engineered',
    'app_lat':'degree; vị trí app, không tự đồng nhất với home', 'app_lon':'degree; vị trí app',
    'latitude_home':'degree; home riêng biệt', 'longitude_home':'degree; home riêng biệt',
    'altitude':'m; code raw/3.281; mốc độ cao chưa xác minh độc lập',
    'height':'m; code raw/3.281; khác altitude',
    'v_north':'raw integer; đơn vị chưa xác minh độc lập', 'v_east':'raw integer; đơn vị chưa xác minh độc lập',
    'v_up':'raw integer; đơn vị chưa xác minh độc lập',
    'd_1_angle':'raw integer; không gán yaw, đơn vị/chuyển đổi chưa xác minh',
    'gps_time':'raw uint64; không dùng làm thời gian tuyệt đối đã xác minh',
    'state_info':'raw uint16 flags; diễn giải trong code chưa kiểm nghiệm đầy đủ',
    'crc-packet':'hex CRC16 nhận', 'crc-calculated':'hex CRC16 tính',
}
SENSITIVE={'serial_number','uuid','latitude','longitude','app_lat','app_lon','latitude_home','longitude_home','gps_time','sequence_number'}
def safe_payload(payload,redact=True):
    return {k:('[ẩn]' if redact and k in SENSITIVE else v) for k,v in (payload or {}).items()}

def decode_candidate(candidate,config,cancel=None,retain=True,phase_trace=None):
    """Optional phase_trace records actual attempts for teaching; no decision is changed."""
    r={'candidate':candidate.index,'start':candidate.start,'end':candidate.end,'Fs_Hz':candidate.fs,'decoder_mode':config.mode,
       'status':'pending','error_stage':None,'error':None,'crc16':None,'crc24':None,'payload':None,'attempts':[],
       'intermediates':{'raw_cut':candidate.iq} if retain else {}}
    stage='coarse_CFO_resample'
    try:
        check_cancel(cancel); prep=prepare(candidate)
        stage='synchronization'; packet=synchronize(prep)
        check_cancel(cancel); stage='FFT_channel'; sy=symbols(packet,config.mode,config.equalization)
        r['equalization']=config.equalization
        if retain: r['intermediates'].update(prep=prep,packet=packet,symbols=sy)
        r['sync']={'start_resampled':int(packet.start),'FFO_Hz':float(packet.detected_ffo),'sampling_offset':float(packet.sampling_offset),'coarse_Hz':prep['coarse_estimate_Hz']}
        for phase in range(4):
            check_cancel(cancel)
            stage='QPSK'
            labels=decide(sy['qpsk_input'],phase)
            stage='descramble'
            bits=descramble(labels)
            stage='turbo' if config.mode=='turbo' else 'systematic_unmatching'
            fec=decode_fec(bits['descrambled'], config.mode)
            if phase_trace is not None:
                phase_trace.append({'phase':phase,'labels':labels,'bits':bits,'fec':fec})
            attempt={'phase':phase,'parsed':False,'crc16':None,'crc24':fec.get('crc24')}
            if config.mode=='turbo':
                attempt.update({k:fec[k] for k in ('crc24_received','crc24_calculated','crc24_residue','backend')})
            r['attempts'].append(attempt)
            stage='payload_CRC16'
            try: payload,crc=parse_payload(fec['bytes'])
            except (ValueError,UnicodeError,KeyError) as exc:
                attempt['parse_error']=type(exc).__name__; continue
            attempt.update(parsed=True,crc16=crc)
            # Keep the first parsed failed trial for diagnosis; a passing trial replaces it.
            # Baseline retains its original first-parse stop and continue_crc its prior behavior.
            accepted = crc and (config.mode!='turbo' or fec['crc24'])
            if config.mode=='turbo' and r['payload'] is not None and not accepted:
                continue
            r.update(payload=payload,crc16=crc,crc24=fec.get('crc24'),selected_phase=phase,
                     status='crc_pass' if accepted else 'crc_fail')
            r['fec_info']={k:fec[k] for k in ('parity_used','crc24_checked','input_bits','output_bytes',
                'iterations','backend','crc24_received','crc24_calculated','crc24_residue') if k in fec}
            if retain: r['intermediates'].update(labels=labels,bits=bits,fec=fec)
            if accepted or config.mode not in ('continue_crc','turbo'): break
        if r['payload'] is None: r.update(status='parse_failed',error_stage='payload',error='Không hướng QPSK nào parse được struct.')
    except Cancelled: raise
    except Exception as exc:
        r.update(status='error',error_stage=stage,error=f'{type(exc).__name__}: {exc}')
    return r

def summary(results):
    result = {'candidates':len(results),'parsed':sum(r['payload'] is not None for r in results),
            'crc_pass':sum(r['crc16'] is True for r in results),'crc_fail':sum(r['crc16'] is False for r in results),
            'errors':sum(r['status'] in ('error','parse_failed') for r in results)}
    if any(r.get('decoder_mode')=='turbo' for r in results):
        result.update(crc24_pass=sum(r['crc24'] is True for r in results),
                      crc24_fail=sum(r['crc24'] is False for r in results),
                      crc24_unselected=sum(r['crc24'] is None for r in results),
                      crc24_attempt_pass=sum(a.get('crc24') is True for r in results for a in r['attempts']),
                      crc24_attempt_fail=sum(a.get('crc24') is False for r in results for a in r['attempts']),
                      confirmed=sum(confirmed(r) for r in results))
    return result

def decode_file(path,config=None,cancel=None,progress=None,retain_limit=100):
    config=config or Config(); data=IQFile(path,config)
    if config.mode=='turbo':
        from .turbo import backend
        backend()  # Fail once with an actionable runtime error; never silently use systematic.
    step=int(config.chunk_seconds*config.fs); results=[]
    for chunk_idx,core_start in enumerate(range(0,data.count,step)):
        check_cancel(cancel)
        core_end=min(core_start+step,data.count)
        pad=int(.002*config.fs) if config.boundary=='overlap' else 0
        start=max(0,core_start-pad); end=min(data.count,core_end+pad)
        iq=data.read(start,end)
        candidates=detect(iq,config.fs,start,chunk_idx)
        if config.boundary=='overlap':
            candidates=[c for c in candidates if core_start<=(c.start+c.end)/2<core_end]
        for completed,candidate in enumerate(candidates,1):
            candidate.index=len(results)
            result=decode_candidate(candidate,config,cancel,retain=len(results)<retain_limit)
            results.append(result)
            if progress:
                # Within a chunk, advance only after decoding its candidates.
                fraction=(core_start+(core_end-core_start)*completed/len(candidates))/data.count
                progress(fraction,result)
        if progress: progress(core_end/data.count,None)
    return results

def valid_positions(result):
    if not confirmed(result): return {}
    p=result['payload'] or {}; positions={}
    for name,lat,lon in [('drone','latitude','longitude'),('app','app_lat','app_lon'),('home','latitude_home','longitude_home')]:
        a,b=p.get(lat),p.get(lon)
        if isinstance(a,(int,float)) and isinstance(b,(int,float)) and math.isfinite(a) and math.isfinite(b) and -90<=a<=90 and -180<=b<=180 and a!=0 and b!=0: positions[name]=(a,b)
    return positions

def export(path,results,config,redact=True):
    path=Path(path)
    rows=[{k:v for k,v in r.items() if k!='intermediates'} for r in results]
    rows=[dict(r,payload=safe_payload(r['payload'],redact),confirmed_by_crc16=r['crc16'] is True,confirmed_frame=confirmed(r)) for r in rows]
    document={'config':asdict(config),'summary':summary(results),'redacted':redact,'field_units_and_source':FIELD_SCHEMA,
        'payload_mapping':'DroneSecurity 9ff8198 src/droneid_packet.py::DroneIDPacket.__init__; NOT an independently validated DJI specification',
        'limitations':[('TurboFEC: hard metrics, 4 iterations, CRC24 + CRC16 required' if config.mode=='turbo' else 'systematic-only; no turbo/parity correction or CRC24'),'CRC does not authenticate the transmitter','baseline chunks can split bursts; overlap mode changes threshold context','first 100 intermediates retained; remaining results still decoded'],
        'candidates':rows}
    if path.suffix.lower()=='.csv':
        flat=[dict(candidate=r['candidate'],start=r['start'],end=r['end'],Fs_Hz=r['Fs_Hz'],status=r['status'],decoder_mode=r['decoder_mode'],crc16=r['crc16'],crc24=r['crc24'],confirmed_frame=r['confirmed_frame'],error_stage=r['error_stage'],error=r['error'],**r['payload']) for r in rows]
        columns=sorted(set().union(*(x.keys() for x in flat))) if flat else ['candidate','status']
        with path.open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(flat)
        path.with_suffix('.metadata.json').write_text(json.dumps({k:v for k,v in document.items() if k!='candidates'},ensure_ascii=False,indent=2),encoding='utf-8')
    else: path.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    return document
