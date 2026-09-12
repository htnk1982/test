import hashlib,json,tempfile,unittest
from pathlib import Path

import product_gui_runtime_v52 as p
from target_settings import Targets


class ProductRequestTests(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory(prefix='p08_req_')
        self.root=Path(self.td.name)
        self.src=self.root/'song.wav';self.src.write_bytes(b'not audio yet')
        self.ref=self.root/'reference.zip';self.ref.write_bytes(b'fixture reference')
        self.refsha=hashlib.sha256(self.ref.read_bytes()).hexdigest()
        self.work=self.root/'work';self.session=self.root/'session'

    def tearDown(self):self.td.cleanup()

    def manifest(self):
        return p._body([self.src],self.ref,Targets(),False,self.work,self.session,
                       expected_reference_sha=self.refsha)

    def write(self,value):
        path=self.root/'request.json';p.write_manifest(path,value);return path

    def test_sealed_roundtrip_and_targets(self):
        value=self.manifest();path=self.write(value)
        got=p._read_manifest(path,expected_reference_sha=self.refsha)
        self.assertEqual(got['runtime_id'],p.RUNTIME_ID)
        self.assertEqual(got['targets'],Targets().to_dict())
        self.assertEqual(got['reference_sha256'],self.refsha)

    def test_normal_product_rejects_noncanonical_reference(self):
        with self.assertRaises(ValueError):
            p.make_manifest([self.src],self.ref,Targets(),False,self.work,self.session)

    def test_reference_mutation_after_seal_is_rejected(self):
        path=self.write(self.manifest());self.ref.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            p._read_manifest(path,expected_reference_sha=self.refsha)

    def test_manifest_tamper_is_rejected(self):
        value=self.manifest();path=self.write(value)
        raw=json.loads(path.read_text(encoding='utf-8'));raw['targets']['wav_lufs']=-9
        path.write_text(json.dumps(raw),encoding='utf-8')
        with self.assertRaises(ValueError):
            p._read_manifest(path,expected_reference_sha=self.refsha)

    def test_same_stem_wav_flac_collision_is_rejected(self):
        other=self.root/'song.flac';other.write_bytes(b'x')
        with self.assertRaises(ValueError):
            p._body([self.src,other],self.ref,Targets(),False,self.work,self.session,
                    expected_reference_sha=self.refsha)


if __name__=='__main__':unittest.main()
