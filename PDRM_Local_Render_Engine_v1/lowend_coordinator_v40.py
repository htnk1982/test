"""Integration coordinator for existing Boundary36 complementary low bands.

Step 1 supports reduction plans only. Same-fundamental synthesis and narrow-band
composition MUST NOT be represented as these broad cuts. They remain explicit
unsupported capabilities until their common budget/render adapters are connected.
The application cannot treat this scaffold as a finished taste-trained planner.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import shutil
import numpy as np
import soundfile as sf
import lowend_boundary_lab as renderer
from integration_contract_v40 import RenderSnapshot, Span, digest, valid_hash, capture, integer

VERSION = 'lowend-coordinator-0.1.1'
LIMITS = {'low': 2.0, 'lowmid': 1.5}


@dataclass(frozen=True)
class CutProposal:
    proposal_id: str
    branch: str
    source_frames: tuple[int, ...]
    depth_db: tuple[float, ...]
    reason: str

    def validate(self, snapshot):
        if not isinstance(self.proposal_id, str) or not self.proposal_id or not isinstance(self.reason, str) or not self.reason:
            raise ValueError('Every proposal needs an identity and a reason')
        if self.branch not in LIMITS:
            raise ValueError('Unsupported operation; no substitution by broad EQ')
        nodes = self.source_frames
        if len(nodes) < 2 or len(nodes) != len(self.depth_db):
            raise ValueError('Control nodes and depths disagree')
        for value in nodes: integer(value, 'source control frame')
        if any(b <= a for a, b in zip(nodes, nodes[1:])) or nodes[-1] > snapshot.source.frames:
            raise ValueError('Non-monotone/out-of-source control clock')
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not np.isfinite(v) for v in self.depth_db):
            raise ValueError('Non-finite or non-numeric control')
        d = np.asarray(self.depth_db)
        if np.any(d < 0) or np.any(d > LIMITS[self.branch]):
            raise ValueError('Proposal outside common intervention budget')
        if d[0] != 0 or d[-1] != 0:
            raise ValueError('Control must explicitly return to zero at its endpoints')
        return self


def compile_plan(snapshot: RenderSnapshot, proposals, *, planner_id: str,
                 calibration_sha256: str, assessment: str, evidence_scope: str):
    """Merge controls before touching audio; never process a previous candidate.

    The common bands use max depth, not a sum. Two modules requesting 1.5 dB on
    the same band do not silently request 3 dB. These are control bounds, not a
    proof of local true-peak, subjective quality or correction completeness.
    """
    snapshot.validate()
    if not isinstance(planner_id, str) or not planner_id or not valid_hash(calibration_sha256):
        raise ValueError('Planner/calibration provenance required')
    if assessment not in ('KEEP_SUPPORTED', 'ABSTAIN', 'PARTIAL', 'CANDIDATE'):
        raise ValueError('Explicit assessment required')
    if evidence_scope not in ('engineering_fixture', 'research_observer'):
        raise ValueError('Only explicit LAB evidence is implemented')
    proposals = tuple(proposals)
    if len({p.proposal_id for p in proposals}) != len(proposals):
        raise ValueError('Duplicate proposal identity')
    n = snapshot.physical.frames; sr = snapshot.physical.samplerate
    frames = set(range(0, n, sr // 100)); frames.add(n-1)
    mapped = []
    for proposal in proposals:
        proposal.validate(snapshot)
        knots = tuple(snapshot.clock.nearest(v) for v in proposal.source_frames)
        if knots[0] < 0 or knots[-1] > n or any(b <= a for a, b in zip(knots, knots[1:])):
            raise ValueError('Control knots collapse or leave physical timeline')
        frames.update(v for v in knots if v < n)
        mapped.append((proposal, knots))
    grid = np.array(sorted(frames), dtype=np.int64)
    curves = {key: np.zeros(len(grid)) for key in LIMITS}
    for proposal, knots in mapped:
        depth = np.interp(grid, knots, proposal.depth_db, left=0, right=0)
        curves[proposal.branch] = np.maximum(curves[proposal.branch], depth)
    changed = any(np.any(v) for v in curves.values())
    if changed and assessment not in ('CANDIDATE', 'PARTIAL'):
        raise ValueError('KEEP or ABSTAIN cannot contain audible edits')
    if not changed and assessment in ('CANDIDATE', 'PARTIAL'):
        raise ValueError('An empty edit is not a correction candidate')
    result = dict(schema=1, version=VERSION, snapshot_sha256=snapshot.token,
        source_sha256=snapshot.source.file_sha256, physical_sha256=snapshot.physical.file_sha256,
        planner_id=planner_id, calibration_sha256=calibration_sha256,
        assessment=assessment, evidence_scope=evidence_scope,
        physical_frames=grid.tolist(), low_cut_db=curves['low'].tolist(),
        lowmid_cut_db=curves['lowmid'].tolist(), proposals=[asdict(p) for p in proposals],
        capabilities=['COMPLEMENTARY_LOW_CUT', 'COMPLEMENTARY_LOWMID_CUT'],
        sub_synthesis='NOT_CONNECTED', semantic_quality='NOT_CERTIFIED')
    # Canonical plain JSON is part of the plan contract. Tuples in dataclasses
    # become lists before sealing, so saving/loading cannot invalidate a plan.
    result = json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))
    result['sha256'] = digest(result)
    return result


def validate_plan(plan, snapshot):
    snapshot.validate(); plain = dict(plan); seal = plain.pop('sha256', None)
    if seal != digest(plain) or plan.get('schema') != 1 or plan.get('version') != VERSION:
        raise ValueError('Plan identity/version mismatch')
    if plan.get('snapshot_sha256') != snapshot.token or plan.get('source_sha256') != snapshot.source.file_sha256 or plan.get('physical_sha256') != snapshot.physical.file_sha256:
        raise ValueError('Plan does not belong to both source and prepared audio')
    proposals = []
    for item in plan.get('proposals', []):
        p = dict(item); p['source_frames'] = tuple(p['source_frames']); p['depth_db'] = tuple(p['depth_db'])
        proposals.append(CutProposal(**p))
    rebuilt = compile_plan(snapshot, proposals, planner_id=plan['planner_id'],
        calibration_sha256=plan['calibration_sha256'], assessment=plan['assessment'],
        evidence_scope=plan['evidence_scope'])
    if rebuilt != plan:
        raise ValueError('Plan controls do not match declared proposals')
    return plan


def render(source, physical, destination, snapshot, plan, *, progress=None, chunk_frames=None):
    """Bounded-memory wrapper around the unchanged Boundary36 renderer.

    One common physical snapshot, one differential rendering pass. Audio outside
    the control support is untouched by this stage. Destination must be new.
    No whole-song LUFS gain is applied here. Publication belongs to orchestrator.
    """
    source, physical, destination = map(Path, (source, physical, destination))
    snapshot.verify(source, physical); validate_plan(plan, snapshot)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Existing destination preserved')
    if destination.resolve() in (source.resolve(), physical.resolve()):
        raise ValueError('Source and physical audio are immutable')
    sr = snapshot.physical.samplerate; n = snapshot.physical.frames
    width = chunk_frames if chunk_frames is not None else 8 * sr
    integer(width, 'chunk frames', sr // 2)
    if width > sr * 16: raise ValueError('Unbounded render chunk')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.partial.wav')
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError('Foreign partial output preserved')
    changed = bool(np.any(plan['low_cut_db']) or np.any(plan['lowmid_cut_db']))
    try:
        if not changed:
            shutil.copyfile(physical, temporary)
        else:
            cfg = renderer.Config()
            # Existing filter is 120 ms; a larger half-second context also keeps
            # short last chunks valid. Global control knots remain source-based.
            pad = max(round(cfg.filter_seconds * sr) // 2 + 2, sr // 2)
            times = np.asarray(plan['physical_frames'], dtype=np.float64) / sr
            with sf.SoundFile(physical) as inp, sf.SoundFile(temporary, 'w',
                    samplerate=sr, channels=2, format='WAV', subtype='DOUBLE') as out:
                for start in range(0, n, width):
                    stop = min(n, start+width); a = max(0, start-pad); b = min(n, stop+pad)
                    inp.seek(a); x = inp.read(b-a, dtype='float64', always_2d=True)
                    cp = dict(time=times-a/sr, low_cut_db=plan['low_cut_db'], lowmid_cut_db=plan['lowmid_cut_db'])
                    y = renderer.render_array(x, sr, cp, cfg, strength=1.)
                    out.write(y[start-a:stop-a])
                    if progress: progress.set('LOWEND_COMMON_RENDER', stop, n)
        snapshot.verify(source, physical)
        result = capture(temporary)
        if (result.frames, result.samplerate, result.channels) != (n, sr, 2):
            raise RuntimeError('Low-end output geometry changed')
        if not changed and result != snapshot.physical:
            raise RuntimeError('Null plan did not preserve original prepared bytes')
        if destination.exists(): raise FileExistsError('Destination appeared; preserved')
        os.rename(temporary, destination)
        return dict(version=VERSION, plan_sha256=plan['sha256'], snapshot_sha256=snapshot.token,
            assessment=plan['assessment'], control_requested=changed,
            waveform_changed=result.pcm_sha256 != snapshot.physical.pcm_sha256,
            output_identity=asdict(result), old_note_sub_called=False,
            sub_synthesis='NOT_CONNECTED', subjective_quality='NOT_EVALUATED')
    except BaseException:
        if temporary.is_file() and not temporary.is_symlink(): temporary.unlink()
        raise
