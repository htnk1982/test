import unittest
import numpy as np

from pdrm_engine.limiter import release_max_envelope


class LimiterEnvelopeTests(unittest.TestCase):
    def test_vectorized_release_matches_scalar_reference(self):
        rng = np.random.default_rng(12345)
        desired = np.maximum(0.0, rng.normal(0.25, 0.8, 200000))
        desired[::997] += 4.0
        r = 0.99973

        reference = np.empty_like(desired)
        state = 0.0
        for i, d in enumerate(desired):
            state = max(float(d), state * r)
            reference[i] = state

        actual = release_max_envelope(desired, r, block_size=4096)
        self.assertTrue(np.allclose(reference, actual, rtol=2e-12, atol=2e-12))

    def test_zero_release_is_instant(self):
        desired = np.array([0.0, 2.0, 0.0, 1.0])
        self.assertTrue(np.array_equal(release_max_envelope(desired, 0.0), desired))


if __name__ == "__main__":
    unittest.main()
