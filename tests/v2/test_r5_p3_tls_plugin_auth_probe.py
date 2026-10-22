from __future__ import annotations

import asyncio
import json
import unittest

from scripts.r5_p3_tls_plugin_auth_probe import run_probe


class R5P3TlsPluginAuthProbeTests(unittest.TestCase):
    def test_probe_combines_tls_auth_and_reconnect(self) -> None:
        report = asyncio.run(run_probe())

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["checks"]["tls_handshake"])
        self.assertTrue(report["checks"]["plugin_auth"])
        self.assertTrue(report["checks"]["command_round_trip"])
        self.assertTrue(report["checks"]["old_token_revoked"])
        self.assertTrue(report["checks"]["new_token_reconnected"])
        self.assertNotIn("PRIVATE KEY", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
