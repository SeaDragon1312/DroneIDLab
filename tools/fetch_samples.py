"""Tải đúng hai mẫu công khai; không đọc đường dẫn ngoài bản nộp."""
from pathlib import Path
import hashlib,json,sys,urllib.request

ROOT=Path(__file__).resolve().parents[1]
COMMIT='9ff819843bee48fb140a0704ec78aff757896dea'
SAMPLES={'mini2_sm':'5a17913cb11cde2919347054700345c9e5595eaff7818980d332b8ac8910bc55',
         'mavic_air_2':'623fa40f190d3fd859ec2fd62b379ad9a01a0485db3179ae29ac2e3c7a070450'}

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    folder=ROOT/'samples';folder.mkdir(exist_ok=True)
    receipts={}
    for name,digest in SAMPLES.items():
        path=folder/name
        url=f'https://raw.githubusercontent.com/RUB-SysSec/DroneSecurity/{COMMIT}/samples/{name}'
        if path.exists():data=path.read_bytes();origin='existing file, hash checked'
        else:
            with urllib.request.urlopen(url,timeout=60) as response:data=response.read()
            origin='downloaded from pinned URL'
        actual=hashlib.sha256(data).hexdigest()
        if actual!=digest:raise RuntimeError(f'{name}: SHA-256 không khớp, không ghi đè file.')
        if not path.exists():path.write_bytes(data)
        receipts[name]={'url':url,'sha256':actual,'bytes':len(data),'source':origin}
        print(f'{name}: {len(data)} byte, SHA-256 đúng.')
    (folder/'manifest.json').write_text(json.dumps(receipts,indent=2),encoding='utf8')

if __name__=='__main__':main()
