"""Checks the visual fixture stays independent of user storage and private data."""
import unittest
from tools.visual_audit_server import Fixture, create_app


class VisualFixtureTests(unittest.TestCase):
    def test_only_synthetic_profiles_and_example_networks_are_created(self):
        data = Fixture()
        self.assertEqual(len(data.accounts), 120)
        for row in data.accounts:
            self.assertTrue(row['username'].startswith('qa_'))
            self.assertEqual(row['password'], '')
            self.assertEqual(row['auth_token'], '')
            self.assertEqual(row['ct0_token'], '')
            self.assertTrue(row['proxy'].startswith('proxy.example'))
            self.assertTrue(row['proxy_ip'].startswith('203.0.113.'))

    def test_locales_and_large_lists_do_not_change_wire_fields(self):
        data = Fixture('light', 'uk', count=5000)
        self.assertEqual(data.preferences['language'], 'uk')
        self.assertEqual(data.preferences['theme'], 'light')
        self.assertEqual(data.snapshot()['summary']['all'], 5000)
        self.assertEqual(set(data.accounts[0]), set(Fixture().accounts[0]))

    def test_application_serves_only_its_static_tree_and_fixture_endpoints(self):
        app = create_app()
        resources = str(list(app.router.resources()))
        self.assertIn('/api/', resources)
        self.assertIn('/__qa/reset', resources)
        self.assertNotIn('browser_profiles', resources)
