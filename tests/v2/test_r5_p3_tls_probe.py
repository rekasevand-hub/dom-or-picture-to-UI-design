from __future__ import annotations

import asyncio
import json
import unittest

from scripts.r5_p3_tls_probe import run_probe


class R5P3TlsProbeTests(unittest.TestCase):
    def test_probe_performs_real_local_tls_handshake(self) -> None:
        report = asyncio.run(run_probe())

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["checks"]["handshake"])
        self.assertTrue(report["checks"]["round_trip"])
        self.assertNotIn("PRIVATE KEY", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
