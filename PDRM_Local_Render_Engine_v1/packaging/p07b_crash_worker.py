"""Test-only hard-death worker using the same owned-workspace primitive."""
from pathlib import Path
import argparse,time
import crash_recovery_v43 as recovery
from integration_contract_v40 import capture,digest

def main():
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('work',type=Path)
    a=ap.parse_args();ident=capture(a.source);request=digest(dict(test='P07B_HARD_KILL',source=ident.file_sha256))
    # Deterministic kill window: create the exact sealed workspace used by the
    # publication path, then emulate a large unfinished render until terminated.
    with recovery.owned_workspace(a.work,source_sha256=ident.file_sha256,request_sha256=request) as owned:
        (owned/'unfinished_audio.bin').write_bytes(b'PDRM'*2*1024*1024)
        (owned/'READY').write_text('kill me',encoding='utf-8')
        while True:time.sleep(1)

if __name__=='__main__':main()
