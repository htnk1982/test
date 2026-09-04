import unittest

from pdrm_engine.contract import ContractError, normalize_config, validate_runtime_context


class Runtime:
    max_round_allowed = 8


class ContractTests(unittest.TestCase):
    def test_runtime_context_required(self):
        with self.assertRaises(ContractError):
            validate_runtime_context(None)

    def test_runtime_round_cap_enforced(self):
        class TooNew:
            max_round_allowed = 9
        with self.assertRaises(ContractError):
            validate_runtime_context(TooNew())

    def test_valid_runtime(self):
        validate_runtime_context(Runtime())

    def test_round9_config_rejected(self):
        with self.assertRaises(ContractError):
            normalize_config({"round9_enabled": True})
        with self.assertRaises(ContractError):
            normalize_config({"requested_round": 9})

    def test_default_round_lock(self):
        cfg = normalize_config({})
        self.assertFalse(cfg["round9_enabled"])
        self.assertEqual(cfg["requested_round"], 8)


if __name__ == "__main__":
    unittest.main()
