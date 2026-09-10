"""Test-only hard-death worker using the same owned-workspace primitive."""
from pathlib import Path
import argparse,os,sys,time
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import crash_recovery_v43 as recovery
from integration_contract_v40 import capture,digest

def main():
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('work',type=Path)
    a=ap.parse_args();ident=capture(a.source);request=digest(dict(test='P07B_HARD_KILL',source=ident.file_sha256))
    # Deterministic kill window: create the exact sealed workspace used by the
    # publication path, persist an unfinished large payload, then signal READY.
    with recovery.owned_workspace(a.work,source_sha256=ident.file_sha256,request_sha256=request) as owned:
        payload=owned/'unfinished_audio.bin'
        with payload.open('wb') as f:
            f.write(b'PDRM'*2*1024*1024);f.flush();os.fsync(f.fileno())
        ready=owned/'READY';ready.write_text('kill me',encoding='utf-8')
        with ready.open('rb') as f:os.fsync(f.fileno())
        print('P07B_WORKER_READY '+str(owned),flush=True)
        while True:time.sleep(1)

if __name__=='__main__':main()
