# A folder bundle; no self-updater or installer is included.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata
root = Path(SPECPATH)
datas, binaries, hidden = [], [], []
for name in ('openvino', 'openvino_genai', 'openvino_tokenizers'):
    d, b, h = collect_all(name)
    datas += d
    binaries += b
    hidden += h
for name in ('openvino', 'openvino-genai', 'openvino-tokenizers', 'openvino-telemetry', 'numpy'):
    datas += copy_metadata(name)
a = Analysis([str(root / 'file_window.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['torch', 'tensorflow', 'jax', 'transformers', 'huggingface_hub',
                       'pytest', 'IPython', 'matplotlib'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LocalScribeNPU',
          debug=False, strip=False, upx=False, console=False, uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='LocalScribeNPU')
