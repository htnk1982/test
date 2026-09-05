from PyInstaller.utils.hooks import collect_all, copy_metadata
from pathlib import Path
root=Path(SPECPATH).parent
datas=[];binaries=[];hidden=[]
for name in ('openvino','openvino_genai','openvino_tokenizers'):
    d,b,h=collect_all(name);datas+=d;binaries+=b;hidden+=h
for name in ('openvino','openvino-genai','openvino-tokenizers','numpy','openvino-telemetry'):
    datas+=copy_metadata(name)
a=Analysis([str(root/'native_host'/'worker.py')],pathex=[str(root)],binaries=binaries,datas=datas,
           hiddenimports=hidden,excludes=['torch','tensorflow','transformers','huggingface_hub'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='WhisperWorker',console=True,upx=False)
coll=COLLECT(exe,a.binaries,a.datas,name='WhisperWorker',upx=False)
