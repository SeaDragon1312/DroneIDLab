"""Check Python/Tk and instantiate the actual supplied Turbo module, without IQ."""
from pathlib import Path
import sys,json,platform,importlib.metadata as meta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from droneid_lab.turbo import backend

def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    try:
        import tkinter as tk
        window=tk.Tk();window.withdraw();window.update();window.destroy()
        runtime=backend()
    except Exception as exc:
        print(f'Kiểm tra không đạt: {exc}',file=sys.stderr);raise SystemExit(1)
    print(json.dumps({'OS':platform.platform(),'Python':platform.python_version(),'Tk':tk.TkVersion,
        'Node':runtime.version,'Turbo_ABI':1,'backend':'supplied WASM SIMD / Node',
        'packages':{name:meta.version(name) for name in ['numpy','scipy','matplotlib','bitarray','crcmod']}},ensure_ascii=False,indent=2))
    print('Runtime sẵn sàng. Chạy: .\\.venv\\Scripts\\python.exe launch.py')

if __name__=='__main__':main()
