"""The launch preference must survive legacy data and bulk changes safely."""
import importlib.util
import unittest
from pathlib import Path


path = Path(__file__).resolve().parents[1] / "xgenius" / "auto_login_policy.py"
spec = importlib.util.spec_from_file_location("auto_login_policy", path)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class AutoLoginPolicyTests(unittest.TestCase):
    def test_legacy_profiles_keep_previous_sign_in_behaviour(self):
        self.assertTrue(policy.is_auto_login_enabled({"username": "legacy"}))
        self.assertFalse(policy.is_auto_login_enabled({"username": "manual", "auto_login": False}))

    def test_bulk_change_only_selected_profiles(self):
        accounts = [{"username": "one"}, {"username": "two", "auto_login": False},
                    {"username": "three", "auto_login": True}]
        self.assertEqual(policy.apply_auto_login(accounts, ["one", "two"], False), 2)
        self.assertEqual([a.get("auto_login") for a in accounts], [False, False, True])
        self.assertEqual(policy.apply_auto_login(accounts, ["one", "two"], True), 2)
        self.assertEqual([a["auto_login"] for a in accounts], [True, True, True])

    def test_invalid_selection_does_not_partially_change_profiles(self):
        accounts = [{"username": "one"}, {"username": "two", "auto_login": False}]
        before = [dict(a) for a in accounts]
        with self.assertRaises(ValueError):
            policy.apply_auto_login(accounts, ["one", "missing"], True)
        self.assertEqual(accounts, before)
        with self.assertRaises(ValueError):
            policy.apply_auto_login(accounts, ["one"], "false")
        self.assertEqual(accounts, before)


if __name__ == "__main__":
    unittest.main()
