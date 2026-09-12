from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import observer_runtime_client_v47 as client


def test_persistent_session_protocol_constants_are_stable():
    assert client.SESSION_VERSION == 'pdrm-observer-session-0.1.0'
    assert client.SESSION_ERROR_VERSION == 'pdrm-observer-session-error-0.1.0'


def test_response_validation_accepts_persistent_metadata_without_weakening_contract():
    request = {
        'schema': 1,
        'version': client.REQUEST_VERSION,
        'source_sha256': 'a' * 64,
        'sha256': 'b' * 64,
    }
    manifest = {'sha256': 'c' * 64, 'model_asset_sha256': 'd' * 64}
    response = {
        'schema': 1,
        'version': client.RESPONSE_VERSION,
        'request_sha256': request['sha256'],
        'arrays': {
            'time': [0.0, 0.01],
            'low_power': np.ones((2, 2, 5)).tolist(),
            'body_power': np.ones((2, 2, 5)).tolist(),
            'focus_power': np.ones((2, 2, 5)).tolist(),
            'upper_focus_power': np.ones((2, 2, 5)).tolist(),
            'bass_f0_hz': np.zeros((2, 2)).tolist(),
            'bass_periodicity': np.zeros((2, 2)).tolist(),
        },
        'meta': {
            'source_sha256': request['source_sha256'],
            'runtime_manifest_sha256': manifest['sha256'],
            'model_asset_sha256': manifest['model_asset_sha256'],
            'source_order': list(client.SOURCE_ORDER),
            'stem_audio_persisted': False,
            'stem_audio_in_master': False,
            'network_downloads_allowed': False,
            'worker_pid': 1234,
            'persistent_session': True,
        },
    }
    arrays, meta = client._validate_response(response, request, manifest)
    assert arrays['low_power'].shape == (2, 2, 5)
    assert meta['persistent_session'] is True
    assert meta['worker_pid'] == 1234
