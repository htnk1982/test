"""PDRM v3.5 LAB: groove-first low-end controller; HE/HFTC/OPPO remain unchanged."""
from contextlib import contextmanager
from pathlib import Path
import natural_finish as base
import auto_peak_v34 as auto_peak
import groove_conditioned_v35 as groove_conditioned
import workspace_cleanup

io=base.io;legacy=base.legacy;FILES=base.FILES
VERSION='natural-finish-3.5.0-groove-lab'
IDENTITY_MODULES=base.IDENTITY_MODULES+(
    'natural_finish_v35.py','groove_conditioned_v35.py','groove_lowend_lab.py','auto_peak_v34.py',
    'offline_peak_stream_v34.py','offline_peak_stream_v32.py','offline_peak_context_v34.py','workspace_cleanup.py')
verify_final=base.verify_final

@contextmanager
def _runtime(source):
    with base._LOCK,groove_conditioned.semantic_source(source):
        old=(base.oppo,base.conditioned,base.VERSION,base.IDENTITY_MODULES)
        try:
            base.oppo=auto_peak;base.conditioned=groove_conditioned;base.VERSION=VERSION;base.IDENTITY_MODULES=IDENTITY_MODULES
            yield
        finally:base.oppo,base.conditioned,base.VERSION,base.IDENTITY_MODULES=old

def _finalize(report,final):
    prep=report.get('peak_preparation') or {};master=report.get('master_peak') or {};codec=report.get('codec_branch') or {}
    prep_route=prep.get('prep_route','UNKNOWN');master_route=master.get('auto_route','UNKNOWN');trials=codec.get('trials') or []
    codec_routes=[t.get('waveform_report',{}).get('auto_route','UNKNOWN') for t in trials]
    prep_lim=bool(prep.get('prep_limiter_used'));master_lim=bool(master.get('conventional_limiter_used'))
    codec_lim=any(bool(t.get('waveform_report',{}).get('conventional_limiter_used')) for t in trials)
    report.update(preparation='auto_safe',preparation_policy='GAIN_ONLY -> OPPO -> LIMITER_ONLY_AFTER_NOT_FEASIBLE',
        internal_orchestration_sentinel='gain_only',preparation_route=prep_route,master_route=master_route,codec_routes=codec_routes,
        prep_limiter_used=prep_lim,final_conventional_limiter_used=master_lim,codec_conventional_limiter_used=codec_lim,
        conventional_limiter_used=prep_lim or master_lim or codec_lim,
        chain=f'HarmonicElasticity -> PREP_AUTO[{prep_route}] -> Groove Low-End -> HFTC -> MASTER_AUTO[{master_route}]',
        execution_profile='V3.5_GROOVE_LOWEND_LAB')
    io.atomic_json(final/'RUN_REPORT.json',report);mq=report['master_metrics'];cq=report.get('codec_metrics')
    text=(f'# PDRM v3.5 Groove LAB — {report.get("source_name","")}\n\n'
          f'前段: {prep_route}。最終WAV: {master_route}。\n'
          '低域: Groove-First lab（attack保護、tail/valley抑制、自動octave-down禁止、同一基音のみ保守的補強）。\n'
          'Observerは解析専用。公開音声は元2mix処理のみ。HFTC/HarmonicElasticity/OPPOのDSP核は変更していません。\n\n'
          f'WAV: {mq["lufs_i"]:.4f} LUFS / TP推定 {mq["true_peak_max_dbtp_estimate"]:.4f} dBTP。\n')
    if cq:text+=f'MP3: {cq["lufs_i"]:.4f} LUFS / TP推定 {cq["true_peak_max_dbtp_estimate"]:.4f} dBTP。\n'
    text+='\nLAB版。低域の聴感承認前にproduction版へ昇格しません。\n';(final/'完了.md').write_text(text,encoding='utf-8')
    for p in final.iterdir():
        if p.is_file() and p.name!='PROOF.json':io.sync_owned_file(p)
    io.atomic_json(final/'PROOF.json',dict(identity=report['identity'],files={p.name:io.file_hash(p) for p in final.iterdir() if p.is_file() and p.name!='PROOF.json'}));return report

def run_file(source,root,*,targets=None,write_mp3=True,interrupt_after=None,preparation='auto_safe'):
    if preparation not in ('auto_safe','gain_only'):raise ValueError('v3.5 lab accepts automatic safety policy only')
    with _runtime(source):
        report,final=base.run_file(source,root,targets=targets,write_mp3=write_mp3,interrupt_after=interrupt_after,preparation='gain_only')
        report=_finalize(report,final)
        if report.get('rerun_status'):report['rerun_status']='IDEMPOTENT_SKIP'
        return report,final

def cleanup_source_workspace(source,root,*,success=False,error=None,prestart=False):
    root=Path(root).resolve();results=[workspace_cleanup.cleanup_source(root,source,current_version=VERSION,success=success,error=error,prestart=prestart)]
    return dict(removed=[p for r in results for p in r.get('removed',[])],bytes_freed=sum(r.get('bytes_freed',0) for r in results),
        diagnostic=next((r.get('diagnostic') for r in results if r.get('diagnostic')),None),success=bool(success))
