"""Verify the fixed, local model before native code sees it. No download path."""
from pathlib import Path
import hashlib

MODEL_ID = 'OpenVINO/whisper-large-v3-turbo-int8-ov'
REVISION = '4929ae83ea2d1df59f4b5898a9aab8aa1c29e711'
HASHES = {
 'config.json': 'bfd92c097547ab12cb42abae8008be5a59a91fdc5ab39acce24489eb8a3e8a86',
 'generation_config.json': '4617fcca458af3b91a103143aaac919c1ab6680b552d7abd10811b7248bd77b4',
 'preprocessor_config.json': '654cf18d3e163b948ceaf9766da56ce0b52de265d58673cf61c9376f126bd499',
 'openvino_encoder_model.xml': '60713d4ed3a8ac8ee020e11c4737ec276d14cabc6a082537bddf2c00ba6ce070',
 'openvino_encoder_model.bin': '0590a8f35f96d57801c55990028d917821ac721026e34b7f3f59d7561fc908e6',
 'openvino_decoder_model.xml': 'aeb09fafbf1c0cbf84baf30f46763436005822faf3b365359b8de0aa04f03047',
 'openvino_decoder_model.bin': 'c064991cbafc4381567d29972b7013dc24026de9c326d03eb1e6e4fc44aa959f',
 'openvino_tokenizer.xml': 'cba304e7bad54773b9d2cbccfbc8501117ecf2e3c0f4f5331742a0a3c9feed93',
 'openvino_tokenizer.bin': 'adfa3d9a2920d0f314121270a960ab331ec0f05838544bb8ecaaa422282a6fd4',
 'openvino_detokenizer.xml': '6e106a14f14b0771b46b7948a99b1d819ff93b2455b7da8f47761ab9dba9dc56',
 'openvino_detokenizer.bin': 'f2b3c47825a1089525ff65c0c8e49271e1dee69a401a04fc827ac2de5b7766e4',
}

def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def verify_model(directory: Path) -> None:
    directory = Path(directory)
    for name, expected in HASHES.items():
        path = directory / name
        if not path.is_file():
            raise ValueError('MODEL_MISSING: ' + name)
        if digest(path) != expected:
            raise ValueError('MODEL_HASH_MISMATCH: ' + name)
