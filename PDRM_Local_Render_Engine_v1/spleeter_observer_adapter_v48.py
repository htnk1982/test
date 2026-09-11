"""PDRM observer adapter for the isolated Spleeter runtime.

This is the only bridge from the Python 3.12 mastering process to the packaged
Python 3.11/TensorFlow observer. It returns the existing role-observer schema;
no stem sample crosses this boundary and no TensorFlow import occurs here.
"""
from __future__ import annotations
from pathlib import Path
import json
import observer_runtime_client_v47 as client
from integration_contract_v40 import digest,file_hash,valid_hash

VERSION='spleeter-observer-adapter-0.1.0'
PROVIDER='spleeter_runtime48'
EXPECTED_MODEL_ASSET_SHA256='3adb4a50ad4eb18c7c4d65fcf4cf2367a07d48408a5eb7d03cd20067429dfaa8'
ROLE_SCHEMA='role-observer-0.2.0'


class SpleeterRuntimeObserver:
    def __init__(self,runtime,*,timeout=240,work_root=None):
        self.runtime=Path(runtime).absolute();self.timeout=timeout;self.work_root=None if work_root is None else Path(work_root).absolute();self._identity=None

    def _inspect(self):
        runtime,python,worker,manifest=client.runtime_identity(self.runtime)
        if manifest.get('model_asset_sha256')!=EXPECTED_MODEL_ASSET_SHA256:
            raise RuntimeError('Unrecognized Spleeter model asset')
        if manifest.get('source_order')!=['mix','drums','bass','other','vocals']:
            raise RuntimeError('Observer source order changed')
        pp=manifest.get('preprocessing',{})
        expected=dict(separator_rate_hz=44100,feature_rate_hz=12000,feature_hop_samples=120,feature_window_samples=720,
            bands_hz=dict(low=[25,120],body=[120,300],focus=[300,450],upper_focus=[450,700]),contexts_required=2,max_core_seconds=16,max_pad_seconds=4)
        if pp!=expected:raise RuntimeError('Observer preprocessing changed without recalibration')
        if manifest.get('offline_policy')!=dict(model_download_at_runtime=False,stem_audio_persisted=False,stem_audio_in_master=False):
            raise RuntimeError('Observer offline/output policy changed')
        identity=dict(provider=PROVIDER,evidence_scope='deployable_observer',model='SPLEETER_4STEMS_V1_4_0',
            model_asset_sha256=manifest['model_asset_sha256'],runtime_manifest_sha256=manifest['sha256'],worker_sha256=manifest['worker_sha256'],
            worker_version=manifest['worker_version'],packages=manifest['packages'],preprocessing_sha256=digest(pp),
            client_sha256=file_hash(Path(__file__).with_name('observer_runtime_client_v47.py')),adapter_sha256=file_hash(__file__),
            stem_audio_in_master=False,runtime_model_download=False)
        return identity

    def identity(self):
        current=self._inspect()
        if self._identity is None:self._identity=json.loads(json.dumps(current,sort_keys=True))
        elif current!=self._identity:raise RuntimeError('Observer runtime identity changed during job')
        return self._identity

    def preflight(self):
        if isinstance(self.timeout,bool) or not isinstance(self.timeout,(int,float)) or not 30<=self.timeout<=900:raise ValueError('Invalid observer timeout')
        if self.work_root is not None:
            self.work_root.mkdir(parents=True,exist_ok=True)
            if self.work_root.is_symlink():raise ValueError('Linked observer work root refused')
        self.identity();return self

    def observe(self,source,start,end,progress=None):
        self.preflight();before=self.identity()
        arrays,raw=client.observe_dual(self.runtime,source,start,end,(1.,2.),work_root=self.work_root,timeout=self.timeout,progress=progress)
        if raw.get('model_asset_sha256')!=before['model_asset_sha256'] or raw.get('runtime_manifest_sha256')!=before['runtime_manifest_sha256']:
            raise RuntimeError('Observer result came from another runtime/model')
        meta=dict(version=ROLE_SCHEMA,provider=PROVIDER,source_sha256=raw['source_sha256'],source_name=raw['source_name'],
            source_frames=raw['source_frames'],source_samplerate=raw['source_samplerate'],start_seconds=raw['start_seconds'],end_seconds=raw['end_seconds'],
            contexts_seconds=raw['contexts_seconds'],source_order=raw['source_order'],model='SPLEETER_4STEMS_V1_4_0',
            model_sha256=raw['model_asset_sha256'],runtime_manifest_sha256=raw['runtime_manifest_sha256'],worker_version=raw['worker_version'],
            probabilities_calibrated=False,output_audio_uses_stems=False,stem_audio_persisted=False,network_downloads_allowed=False,
            preprocessing_sha256=before['preprocessing_sha256'],reconstruction_error_db=raw.get('reconstruction_error_db'))
        return arrays,meta
