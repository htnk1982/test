"""Actual integration tests. Planner is an explicit engineering fixture.

No neural inference or personal music. The test does not certify the unimplemented
automatic musical planner, but DOES execute the existing production DSP and codec.
"""
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
import json
import numpy as np
import soundfile as sf
import integrated_finish_v40 as app
import integration_contract_v40 as contracts
import lowend_coordinator_v40 as co
import note_sub_lab_v02 as old_ns
from target_settings import Targets

EVIDENCE=[]


def mixture(sr, seconds=2.6):
    t=np.arange(round(sr*seconds))/sr
    bass=.07*np.sin(2*np.pi*61*t)+.025*np.sin(2*np.pi*183*t)
    mid=.08*np.sin(2*np.pi*730*t)+.02*np.sin(2*np.pi*1800*t)
    transient=np.zeros(len(t))
    for start in (.32,1.15,1.99):
        tau=t-start; mask=tau>=0
        transient[mask]+=.16*np.exp(-tau[mask]*100)*np.cos(2*np.pi*95*tau[mask])
    s=bass+mid+transient+.008*np.sin(2*np.pi*9300*t)
    fade=np.minimum(np.clip(t/.03,0,1),np.clip((seconds-t)/.05,0,1))
    return np.column_stack((s*fade,(s+.005*np.sin(2*np.pi*400*t))*fade))


class FixturePlanner:
    def __init__(self, mode='keep', failure=None):
        self.mode=mode;self.failure=failure;self.calls=0;self.last_context=None
    def identity(self):
        return dict(planner_id='ENGINEERING_FIXTURE_'+self.mode,
            calibration_sha256=contracts.digest({'purpose':'routing test only','mode':self.mode}),
            evidence_scope='engineering_fixture')
    def preflight(self):
        if self.failure=='preflight':raise RuntimeError('Model/planner is unavailable')
    def build(self, context, progress=None):
        self.calls+=1; self.last_context=context
        if self.failure=='io':raise OSError('Injected analysis I/O failure')
        if self.failure=='cancel':raise InterruptedError('Injected cancellation')
        if self.failure=='none':return None
        if self.failure=='mutate':
            x,sr=sf.read(context.source_path);sf.write(context.source_path,x*.99,sr,subtype='FLOAT')
        props=[]
        if self.mode=='cut':
            sr=context.snapshot.source.samplerate
            props=[co.CutProposal('hit-control','low',(round(.35*sr),round(.55*sr),round(1.70*sr),round(1.9*sr)),
                                  (0.,1.,1.,0.),'Known fixture time region, NOT automatically detected'),
                   co.CutProposal('occupancy-control','low',(round(.5*sr),round(.7*sr),round(1.5*sr),round(1.8*sr)),
                                  (0.,1.5,1.5,0.),'Overlap tests max budget, NOT independent series processing')]
        pid=self.identity()
        result=co.compile_plan(context.snapshot,props,**pid,assessment='CANDIDATE' if props else ('ABSTAIN' if self.mode=='abstain' else 'KEEP_SUPPORTED'))
        if self.failure=='wrong_snapshot':result['snapshot_sha256']='0'*64
        return result


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'input').mkdir();self.source=self.root/'input'/'試験音源.wav'
        sf.write(self.source,mixture(48000),48000,subtype='FLOAT')
        self.work=self.root/'jobs'
    def tearDown(self):self.temp.cleanup()
    def run_chain(self, planner=None, **kwargs):
        # Legacy generation MUST NOT be used even if the new plan cannot act.
        with patch.object(old_ns,'collect_frames',side_effect=AssertionError('OLD NOTE-SUB CALLED')) as a, \
             patch.object(old_ns,'make_events',side_effect=AssertionError('OLD NOTE EVENTS CALLED')) as b, \
             patch.object(old_ns,'render',side_effect=AssertionError('OLD NOTE RENDER CALLED')) as c:
            result=app.run_lab(self.source,self.work,planner or FixturePlanner(),enable_lab=True,**kwargs)
            a.assert_not_called();b.assert_not_called();c.assert_not_called()
        return result
    def no_work_audio(self):
        self.assertFalse(list(self.work.glob('.integration40_*')))
        for p in self.work.glob('*.failure.json'):self.assertLess(p.stat().st_size,4096)
    def test_release_entry_closed(self):
        with self.assertRaises(RuntimeError):app.run_lab(self.source,self.work,FixturePlanner())
        self.assertFalse(self.work.exists())
    def test_missing_planner_not_noop(self):
        with self.assertRaises(ValueError):app.run_lab(self.source,self.work,None,enable_lab=True)
        self.assertFalse(self.work.exists())
    def test_preflight_before_he(self):
        with patch.object(app.common,'render_harmonic') as h:
            with self.assertRaises(RuntimeError):self.run_chain(FixturePlanner(failure='preflight'))
            h.assert_not_called()
        self.assertFalse(self.work.exists())
    def test_real_wav_mp3_keep_48k(self):
        before=contracts.file_hash(self.source);r,f=self.run_chain()
        self.assertFalse(r['old_note_sub_called']);self.assertFalse(r['lowend_report']['waveform_changed'])
        self.assertTrue(r['intermediate_audio_removed']);self.assertGreater(r['work_bytes_removed'],0)
        self.assertLessEqual(abs(r['master_metrics']['lufs_i']+12),.03)
        self.assertLessEqual(r['master_metrics']['true_peak_max_dbtp_estimate'],-2)
        self.assertLessEqual(abs(r['codec_metrics']['lufs_i']+14),.03)
        self.assertLessEqual(r['codec_metrics']['true_peak_max_dbtp_estimate'],-2)
        self.assertEqual(contracts.file_hash(self.source),before);self.assertTrue((f/'PROOF.json').exists())
        self.no_work_audio();EVIDENCE.append(self.record(r,'KEEP_48000'))
    def test_actual_overlap_plan_with_codec_rates(self):
        for sr,subtype in ((44100,'PCM_24'),(96000,'FLOAT')):
            with self.subTest(sr=sr):
                sf.write(self.source,mixture(sr),sr,subtype=subtype)
                r,f=self.run_chain(FixturePlanner('cut'))
                self.assertTrue(r['lowend_report']['waveform_changed']);self.assertEqual(r['sub_synthesis'],'NOT_CONNECTED')
                self.assertEqual(r['master_metrics']['samplerate'],sr)
                self.assertEqual(r['codec_metrics']['samplerate'],min(sr,48000))
                self.assertLessEqual(abs(r['master_metrics']['lufs_i']+12),.03)
                self.assertLessEqual(abs(r['codec_metrics']['lufs_i']+14),.03)
                self.no_work_audio();EVIDENCE.append(self.record(r,'CUT_'+str(sr)))
    def test_explicit_abstention_not_reported_healthy(self):
        r,f=self.run_chain(FixturePlanner('abstain'),write_mp3=False)
        self.assertEqual(r['lowend_assessment'],'ABSTAIN');self.assertFalse(r['calibration_is_personal_taste_approval'])
        self.assertFalse((f/'LISTEN_320kbps.mp3').exists());self.no_work_audio()
    def test_actual_tight_target_profile(self):
        r,f=self.run_chain(FixturePlanner('cut'),targets=Targets(wav_lufs=-10.,wav_tp=-2.,mp3_lufs=-14.,mp3_tp=-2.))
        self.assertLessEqual(abs(r['master_metrics']['lufs_i']+10),.03)
        self.no_work_audio();EVIDENCE.append(self.record(r,'STRESS_MINUS10'))
    def test_idempotent_proof_no_new_plan(self):
        p=FixturePlanner();r,f=self.run_chain(p,write_mp3=False)
        h=contracts.file_hash(f/'MASTER.wav');r2,f2=self.run_chain(p,write_mp3=False)
        self.assertEqual(p.calls,1);self.assertEqual(f,f2);self.assertEqual(r2['rerun_status'],'IDEMPOTENT_SKIP')
        self.assertEqual(contracts.file_hash(f/'MASTER.wav'),h)
    def test_modified_output_never_replaced(self):
        p=FixturePlanner();r,f=self.run_chain(p,write_mp3=False);(f/'MASTER.wav').write_bytes(b'foreign')
        with self.assertRaises(RuntimeError):self.run_chain(p,write_mp3=False)
        self.assertEqual((f/'MASTER.wav').read_bytes(),b'foreign')
    def test_planner_io_failure_no_audio_and_no_musical_fallback(self):
        with self.assertRaises(OSError):self.run_chain(FixturePlanner(failure='io'),write_mp3=False)
        self.no_work_audio();self.assertFalse(list(self.work.rglob('*.wav')))
    def test_cancel_removes_large_work(self):
        with self.assertRaises(InterruptedError):self.run_chain(FixturePlanner(failure='cancel'),write_mp3=False)
        self.no_work_audio();self.assertFalse(list(self.work.rglob('*.wav')))
    def test_none_plan_not_default_dry_success(self):
        with self.assertRaises(ValueError):self.run_chain(FixturePlanner(failure='none'),write_mp3=False)
        self.no_work_audio();self.assertFalse(list(self.work.glob('INTEGRATION_LAB_*')))
    def test_snapshot_tamper_stops(self):
        with self.assertRaises(ValueError):self.run_chain(FixturePlanner(failure='wrong_snapshot'),write_mp3=False)
        self.no_work_audio();self.assertFalse(list(self.work.glob('INTEGRATION_LAB_*')))
    def test_planner_cannot_mutate_source(self):
        with self.assertRaises(ValueError):self.run_chain(FixturePlanner(failure='mutate'),write_mp3=False)
        self.no_work_audio();self.assertFalse(list(self.work.glob('INTEGRATION_LAB_*')))
    def test_foreign_source_directory_never_cleaned(self):
        sentinel=self.source.parent/'unrelated.txt';sentinel.write_text('keep')
        with self.assertRaises(ValueError):app.run_lab(self.source,self.source.parent/'work',FixturePlanner(),enable_lab=True)
        self.assertEqual(sentinel.read_text(),'keep')
    def test_keep_matches_explicit_bypass_chain(self):
        r,f=self.run_chain(write_mp3=False)
        ref=self.root/'reference_path';ref.mkdir()
        he=ref/'he.wav';app.common.render_harmonic(self.source,he)
        prep=ref/'prep.wav';app.auto.fit(he,prep,ref/'prep_work',-14.,-2.5)
        met=app.auto.measure(prep)
        anchor=app.auto.scaled_file(prep,ref/'anchor.wav',-14.-met['lufs_i'])
        t,g,stat=app.hf.analyze_control(anchor,app.hf.Config())
        raw,cache=app.hf.render_raw(prep,ref/'hf',t,g,app.hf.Config())
        out=ref/'float.wav';app.auto.fit(raw,out,ref/'master',-12.,-2.)
        master=ref/'master.wav';app.common.write_pcm24(out,master)
        self.assertEqual(contracts.capture(master).pcm_sha256,contracts.capture(f/'MASTER.wav').pcm_sha256)
        EVIDENCE.append(dict(case='KEEP_EQUIVALENCE',decoded_pcm_equal=True,old_note_sub_called=False))
    def test_persisted_plan_cut_keep_abstain(self):
        class PersistedPlanner(FixturePlanner):
            def build(self,context,progress=None):
                plan=super().build(context,progress)
                return json.loads(json.dumps(plan,ensure_ascii=False,allow_nan=False))
        states=[]
        for mode in ('cut','keep','abstain'):
            with self.subTest(mode=mode):
                p=PersistedPlanner(mode);r,f=self.run_chain(p,write_mp3=False)
                self.assertEqual(r['lowend_report']['waveform_changed'],mode=='cut')
                self.no_work_audio();states.append(r['lowend_assessment'])
        self.assertEqual(states,['CANDIDATE','KEEP_SUPPORTED','ABSTAIN'])
        EVIDENCE.append(dict(case='PERSISTED_PLAN_ROUNDTRIP',states=states,all_completed=True))
    @staticmethod
    def record(r,name):
        return dict(case=name,status=r['status'],old_note_sub_called=r['old_note_sub_called'],
            plan_assessment=r['lowend_assessment'],waveform_changed=r['lowend_report']['waveform_changed'],
            prep_route=r['preparation']['auto_route'],master_route=r['master']['auto_route'],
            codec_routes=[p['auto_report']['auto_route'] for p in r['codec_trials']],
            wav_lufs=r['master_metrics']['lufs_i'],wav_tp=r['master_metrics']['true_peak_max_dbtp_estimate'],
            mp3_lufs=None if r['codec_metrics'] is None else r['codec_metrics']['lufs_i'],
            mp3_tp=None if r['codec_metrics'] is None else r['codec_metrics']['true_peak_max_dbtp_estimate'],
            work_bytes_removed=r['work_bytes_removed'],source_unchanged=r['source_unchanged'],
            evidence_scope=r['planner_evidence_scope'],neural_inference=False,production_release=False)


if __name__=='__main__':unittest.main(verbosity=2)
