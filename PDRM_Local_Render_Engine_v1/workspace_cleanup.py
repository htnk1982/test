"""Delete large OPPO work products after a track is finished or failed.

Only known work roots are touched. Public processed outputs and their .pdrm
receipts are never deleted here. On failure a small JSON diagnostic is retained.
"""
from __future__ import annotations
from pathlib import Path
import json,os,shutil,time
import note_sub_lab as io

VERSION='workspace-cleanup-1.0.0'

def _same_source(record,sha):
    ident=record.get('identity',record) if isinstance(record,dict) else {}
    return ident.get('source_sha256')==sha or ident.get('source')==sha

def _read(path):
    try:return io.read_json(path)
    except Exception:return None

def cleanup_source(root,source,*,current_version=None,success=False,error=None,prestart=False):
    root=Path(root).resolve();source=Path(source).resolve(strict=True);sha=io.file_hash(source)
    removed=[];diagnostic=None
    if not root.exists():return dict(removed=removed,bytes_freed=0,diagnostic=None)
    before=0
    def size(p):
        total=0
        try:
            for f in p.rglob('*'):
                try:
                    if f.is_file():total+=f.stat().st_size
                except OSError:pass
        except OSError:pass
        return total
    # Main per-track jobs. Keep a same-version unfinished job only at prestart so
    # an interrupted v3.2 run can resume. Older versions are stale by definition.
    jobs=root/'.oppo_work_v3'
    if jobs.is_dir():
        for d in list(jobs.iterdir()):
            if not d.is_dir():continue
            rec=_read(d/'identity.json')
            if not rec or not _same_source(rec,sha):continue
            version=rec.get('version')
            if prestart and current_version and version==current_version:continue
            if error and diagnostic is None:
                fail=_read(d/'FAILURE.json')
                diagnostic=dict(source=source.name,source_sha256=sha,error=str(error),failure=fail,
                                timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'))
            before+=size(d);shutil.rmtree(d,ignore_errors=True);removed.append(str(d))
        try:
            if not any(jobs.iterdir()):jobs.rmdir()
        except OSError:pass
    # Verified backend result directories copied to processed are no longer needed.
    for d in list(root.glob('*__OPPO_*')):
        if not d.is_dir():continue
        rec=_read(d/'RUN_REPORT.json') or _read(d/'PROOF.json')
        if rec and _same_source(rec,sha):
            before+=size(d);shutil.rmtree(d,ignore_errors=True);removed.append(str(d))
    # v3.2/v3.1 nested optimizer jobs can exist below alternate roots after failure.
    for base in (root/'master',root/'codec_work'):
        if base.exists() and base.is_dir():
            # These are only safe to remove when the root itself belongs to this
            # source; normal runs keep them under the matched .oppo_work_v3 job,
            # so this branch is primarily defensive.
            pass
    if diagnostic is not None:
        dd=root/'diagnostics';dd.mkdir(parents=True,exist_ok=True)
        name=time.strftime('%Y%m%d_%H%M%S')+'_'+sha[:12]+'.json';p=dd/name
        p.write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2)[:200000],encoding='utf-8');diagnostic=str(p)
    return dict(removed=removed,bytes_freed=before,diagnostic=diagnostic,success=bool(success))
