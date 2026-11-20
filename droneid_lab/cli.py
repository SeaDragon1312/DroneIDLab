import argparse,json,sys
from .pipeline import Config,decode_file,summary,export
def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='Offline DroneID reference laboratory')
    p.add_argument('input');p.add_argument('--fs',type=float,default=50e6);p.add_argument('--fc',type=float)
    p.add_argument('--format',choices=['float32','int16'],default='float32');p.add_argument('--byte-order',choices=['little','big'],default='little')
    p.add_argument('--iq-order',choices=['IQ','QI'],default='IQ');p.add_argument('--mode',choices=['turbo','baseline'],default='turbo')
    p.add_argument('--boundary',choices=['baseline','overlap'],default='baseline');p.add_argument('--output',default='result.redacted.json')
    p.add_argument('--private',action='store_true',help='Export identifiers/coordinates locally')
    p.add_argument('--equalization',choices=['none','zf'],default=None,help='Default: zf for turbo, none for baseline')
    a=p.parse_args();c=Config(fs=a.fs,fc=a.fc,format=a.format,byte_order=a.byte_order,iq_order=a.iq_order,mode=a.mode,boundary=a.boundary,equalization=a.equalization)
    try:
        r=decode_file(a.input,c);export(a.output,r,c,not a.private);print(json.dumps(summary(r)))
        if not r:print('Không tìm thấy burst phù hợp trong file.')
    except Exception as e: p.exit(1,f'{type(e).__name__}: {e}\n')
if __name__=='__main__':main()
