"""Diagnostic launcher: log exists before importing audio dependencies."""
from pathlib import Path
import os
import sys
import time
import traceback

class Tee:
    def __init__(self, terminal, log): self.terminal=terminal; self.log=log
    def write(self, s):
        self.terminal.write(s); self.log.write(s); self.log.flush()
    def flush(self): self.terminal.flush(); self.log.flush()
    def isatty(self): return False

def launch():
    root=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'PDRM_Local_Render_Engine_v1'/'note_sub_lab'
    root.mkdir(parents=True,exist_ok=True)
    path=root/('LAUNCH_DIAGNOSTIC_'+time.strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())+'.txt')
    out,err=sys.stdout,sys.stderr; result=0
    with path.open('w',encoding='utf-8') as log:
        sys.stdout=Tee(out,log); sys.stderr=Tee(err,log)
        try:
            print('PDRM NOTE-FOLLOWING SUB-BASS LAB - EXPERIMENTAL')
            print('Python:',sys.version)
            print('Original C and production engine are not modified. No downloads.')
            import note_sub_lab as lab
            import numpy as np
            t=np.arange(768)/4000
            f,p=lab.nsdf_pitch(np.cos(2*np.pi*82.406889*t)+.5*np.cos(4*np.pi*82.406889*t))
            if f is None or lab.cents(f,82.406889)>10: raise RuntimeError('Small pitch selfcheck failed; rendering was not started')
            lab.main()
        except KeyboardInterrupt:
            print('Interrupted. Completed checkpoints remain.'); result=130
        except Exception:
            traceback.print_exc(); result=1
        finally:
            print('Launcher diagnostic:',path)
            sys.stdout=out;sys.stderr=err
    return result

if __name__=='__main__':sys.exit(launch())
