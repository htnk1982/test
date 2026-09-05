from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("reference_gap",ROOT/"reference_gap.py")
gap=importlib.util.module_from_spec(spec); spec.loader.exec_module(gap)


def tone(sr=48000,seconds=4.0,hz=1000):
    t=np.arange(int(sr*seconds))/sr
    a=0.12*np.sin(2*np.pi*hz*t)
    return np.column_stack((a,a)).astype(np.float64)


def fixture(root):
    job=root/"Round9_synthetic"; (job/"RENDERS").mkdir(parents=True)
    (job/"LAB_INTERNAL").mkdir()
    wav=job/"RENDERS"/"HarmonicElasticity.wav"
    sf.write(wav,tone(seconds=6),48000,subtype="PCM_24")
    h=gap.sha256_file(wav)
    gap.atomic_json(job/"manifest.json",{"experiment_id":"PDRM-v0.6-Round9-HarmonicLoudness-exp1"})
    gap.atomic_json(job/"state.json",{"candidates":{"HarmonicElasticity":{"sha256":h}}})
    gap.atomic_json(job/"LAB_INTERNAL"/"blind_mapping.json",{"C":"HarmonicElasticity"})
    ref=root/"synthetic_reference.wav"
    sf.write(ref,tone(seconds=7,hz=2000),48000,subtype="PCM_24")
    return job,wav,h,ref


class ReferenceGapTests(unittest.TestCase):
    def test_silence_excluded(self):
        self.assertFalse(gap.block_metrics(np.zeros((48000,2)),48000)["included"])
    def test_nonfinite_refused(self):
        x=tone(); x[20,0]=np.nan
        with self.assertRaisesRegex(ValueError,"Non-finite"): gap.block_metrics(x,48000)
    def test_gain_invariance_after_analytical_anchor(self):
        a=gap.block_metrics(tone(),48000); b=gap.block_metrics(tone()*0.25,48000)
        self.assertAlmostEqual(a["measured_lufs"]-b["measured_lufs"],12.04119982656,places=6)
        for key in ("block_plr_tp_db","crest_100ms_p50_db","band/500_1200Hz/rms_dbfs_at_anchor"):
            self.assertAlmostEqual(a["features"][key],b["features"][key],places=5)
    def test_antiphase_does_not_erase_band_power(self):
        x=tone(); a=gap.block_metrics(x,48000); x[:,1]*=-1
        b=gap.block_metrics(x,48000)
        key="band/500_1200Hz/rms_dbfs_at_anchor"
        self.assertAlmostEqual(a["features"][key],b["features"][key],places=7)
    def test_sine_crest_same_definition_across_sample_rates(self):
        for sr in (44100,48000):
            f=gap.block_metrics(tone(sr=sr),sr)["features"]
            self.assertAlmostEqual(f["crest_100ms_p50_db"],3.0103,delta=0.01)
    def test_absent_band_has_no_occupancy_score(self):
        f=gap.block_metrics(tone(),48000)["features"]
        self.assertIsNone(f["band/20_60Hz/400ms/occupancy_6db_below_p90"])
    def test_winner_hash_not_assumed_from_filename(self):
        with tempfile.TemporaryDirectory() as d:
            job,wav,h,ref=fixture(Path(d))
            with self.assertRaisesRegex(ValueError,"not the C"):
                gap.validate_winner(job,"0"*64)
            self.assertEqual(gap.validate_winner(job,h)[1],h)
    def test_full_comparison_is_read_only_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); job,wav,h,ref=fixture(root)
            before={str(p):gap.sha256_file(p) for p in job.rglob("*") if p.is_file()}
            r1=gap.run_comparison(job,ref,root/"out",h,3,1)
            r2=gap.run_comparison(job,ref,root/"out",h,3,1)
            self.assertEqual(r1["comparison"],r2["comparison"])
            self.assertEqual(r2["C"]["computed_blocks"],0)
            self.assertEqual(r2["reference"]["computed_blocks"],0)
            self.assertFalse(r2["audio_written"])
            self.assertTrue(r2["source_unchanged"])
            self.assertEqual(before,{str(p):gap.sha256_file(p) for p in job.rglob("*") if p.is_file()})
            self.assertTrue(list((root/"out").rglob("REFERENCE_GAP_REPORT.md")))
    def test_interruption_retains_block_and_resume_matches_clean(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); job,wav,h,ref=fixture(root)
            with self.assertRaisesRegex(RuntimeError,"Injected interruption"):
                gap.run_comparison(job,ref,root/"out",h,3,1,interrupt_after=1)
            resumed=gap.run_comparison(job,ref,root/"out",h,3,1)
            clean=gap.run_comparison(job,ref,root/"clean",h,3,1)
            self.assertGreaterEqual(resumed["C"]["reused_blocks"],1)
            self.assertEqual(resumed["comparison"],clean["comparison"])
    def test_modified_cache_recomputed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); job,wav,h,ref=fixture(root)
            first=gap.run_comparison(job,ref,root/"out",h,3,1)
            cached=next((root/"out").rglob("C_00000.json"))
            data=gap.load_json(cached); data["payload"]["features"]["block_plr_tp_db"]=999
            gap.atomic_json(cached,data)
            second=gap.run_comparison(job,ref,root/"out",h,3,1)
            self.assertEqual(second["C"]["computed_blocks"],1)
            self.assertEqual(first["comparison"],second["comparison"])
    def test_output_cannot_be_inside_original_job(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); job,wav,h,ref=fixture(root)
            with self.assertRaisesRegex(ValueError,"outside"):
                gap.run_comparison(job,ref,job/"out",h,3,1)
    def test_reference_median_has_no_pass_fail_semantics(self):
        table=gap.comparison_table({"a":{"p50":9}},{"a":{"p10":1,"p50":2,"p90":3}})
        self.assertEqual(table["a"]["descriptive_relation"],"above_reference_p90")
        self.assertNotIn("pass",table["a"])


if __name__=="__main__": unittest.main()
