from __future__ import annotations

import asyncio
import json
import unittest

from scripts.r5_p3_plugin_auth_probe import run_probe


class R5P3PluginAuthProbeTests(unittest.TestCase):
    def test_probe_covers_plugin_token_handshake(self) -> None:
        report = asyncio.run(run_probe())

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["checks"]["missing_rejected"])
        self.assertTrue(report["checks"]["wrong_rejected"])
        self.assertTrue(report["checks"]["valid_accepted"])
        self.assertTrue(report["checks"]["optional_mode_unchanged"])
        self.assertTrue(report["checks"]["rotation_old_rejected"])
        self.assertTrue(report["checks"]["rotation_new_accepted"])
        self.assertNotIn("probe-plugin-secret", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
