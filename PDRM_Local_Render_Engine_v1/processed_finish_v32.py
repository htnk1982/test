"""v3.2 publisher: same-name outputs plus per-track workspace cleanup."""
from __future__ import annotations
import argparse,os,traceback
from pathlib import Path
from target_settings import Targets
import processed_finish as base

VERSION='processed-finish-3.2.0'
io=base.io
run_file=base.run_file
choose_sources=base.choose_sources

def _cleanup(backend,source,root,*,success=False,error=None,prestart=False):
    fn=getattr(backend,'cleanup_source_workspace',None) if backend is not None else None
    if fn is None:return None
    try:
        result=fn(source,root,success=success,error=error,prestart=prestart)
        if result and result.get('bytes_freed'):
            mib=result['bytes_freed']/1024**2
            print(f'[CLEANUP] {source.name}: {mib:.1f} MiB の作業ファイルを削除',flush=True)
        if result and result.get('diagnostic'):
            print('[CLEANUP] 診断だけ保持:',result['diagnostic'],flush=True)
        return result
    except Exception as exc:
        # Cleanup must never make a verified public output look failed.
        print('[CLEANUP WARNING]',source.name,str(exc),flush=True)
        return None

def main(argv=None,*,backend=None,default_root=None)->int:
    parser=argparse.ArgumentParser(description='Same-name WAV/MP3 with per-track cleanup')
    parser.add_argument('sources',nargs='*',type=Path)
    parser.add_argument('--work-root',type=Path)
    for field in ('wav-lufs','wav-tp','mp3-lufs','mp3-tp'):parser.add_argument('--'+field,type=float)
    parser.add_argument('--replace-managed',action='store_true')
    args=parser.parse_args(argv)
    fields={k:getattr(args,k) for k in Targets().to_dict()};targets=None
    if any(v is not None for v in fields.values()):
        targets=Targets(**{k:(v if v is not None else getattr(Targets(),k)) for k,v in fields.items()}).validate()
    sources=choose_sources(args.sources)
    if not sources:
        print('中止しました。原音は変更していません。');return 0
    root=Path(args.work_root or default_root or base.default_work_root()).resolve();root.mkdir(parents=True,exist_ok=True)
    # Remove stale work from older OPPO versions for the selected sources before
    # rendering. A same-version unfinished job is kept so v3.2 interruption can resume.
    for source in sources:
        try:_cleanup(backend,source,root,prestart=True)
        except Exception:pass
    keys,conflicts={},set()
    for source in sources:
        key=(str(source.absolute().parent.resolve()).casefold(),source.stem.casefold())
        if key in keys and source.absolute()!=keys[key]:conflicts.add(key)
        keys[key]=source.absolute()
    failed=0;folders=[]
    for i,source in enumerate(sources,1):
        print(f'[{i}/{len(sources)}] {source.name}',flush=True);ok=False;err=None
        try:
            key=(str(source.absolute().parent.resolve()).casefold(),source.stem.casefold())
            if key in conflicts:raise RuntimeError('同じフォルダに同名のWAV/FLACが選ばれています。どちらか一方を選んでください。')
            kwargs=dict(targets=targets,replace_managed=args.replace_managed)
            if backend is not None:kwargs['backend']=backend
            result,folder=run_file(source,root,**kwargs);ok=True
            print('確認済み（再処理なし）:' if result.get('rerun_status') else '完了:',folder,flush=True)
            for name in result['files']:print(' ',folder/name,flush=True)
            if folder not in folders:folders.append(folder)
        except Exception as exc:
            failed+=1;err=exc
            print('未出力または保存未完了:',source.name,str(exc),flush=True);traceback.print_exc()
        finally:
            # After success all backend caches are disposable because processed/.pdrm
            # owns the publication identity. After a normal per-track failure large
            # audio caches are also deleted; only a compact diagnostic is kept.
            _cleanup(backend,source,root,success=ok,error=err)
    if folders and os.name=='nt':
        try:os.startfile(str(folders[0]))
        except OSError:pass
    return 1 if failed else 0

if __name__=='__main__':raise SystemExit(main())
