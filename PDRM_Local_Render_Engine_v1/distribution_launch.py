"""Create a launch log before importing any DSP dependency."""
from pathlib import Path
import os
import sys
import time
import traceback

class Tee:
    def __init__(self, terminal, log): self.terminal, self.log = terminal, log
    def write(self, text):
        self.terminal.write(text); self.log.write(text); self.log.flush()
    def flush(self): self.terminal.flush(); self.log.flush()
    def isatty(self): return False

def launch():
    root = Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'PDRM_Distribution_v2'/'logs'
    root.mkdir(parents=True,exist_ok=True)
    path = root/('launch_'+time.strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())+'.txt')
    stdout,stderr=sys.stdout,sys.stderr
    with path.open('w',encoding='utf-8') as log:
        sys.stdout,sys.stderr=Tee(stdout,log),Tee(stderr,log)
        try:
            print('PDRM Distribution v2 | HE + peak protection + Note-Sub + HFTC')
            print('Outputs: -12 LUFS WAV, -14 LUFS WAV, -14 LUFS 320kbps MP3')
            print('Python:',sys.version)
            print('Launch log:',path)
            import distribution_finish
            return distribution_finish.main()
        except KeyboardInterrupt:
            print('Interrupted. Completed checkpoints are retained.');return 130
        except Exception:
            traceback.print_exc();return 1
        finally:
            sys.stdout,sys.stderr=stdout,stderr

if __name__=='__main__':raise SystemExit(launch())
