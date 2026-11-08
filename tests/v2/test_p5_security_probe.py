from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p5_security_probe import run_probe

CANARY_VALUES = (
    "probe-bearer-canary-7d2a",
    "probe-query-canary-4c1f",
    "probe-client-token-canary-9b8e",
    "probe-action-text-canary-5a3d",
)


class P5SecurityProbeTests(unittest.TestCase):
    def test_probe_collects_generated_canary_security_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(output)
            serialized = (output / "result.json").read_text(encoding="utf-8")
            persisted = json.loads(serialized)

        self.assertEqual(result["status"], "pass-current-scope")
        self.assertEqual(persisted["content_hash"], result["content_hash"])
        self.assertTrue(result["source_hashes"]["bridge_server"])
        self.assertTrue(result["source_hashes"]["redaction"])
        self.assertTrue(result["source_hashes"]["grounding_reliability"])
        checks = {item["name"]: item["passed"] for item in result["checks"]}
        self.assertTrue(checks["plugin-auth-fail-closed"])
        self.assertTrue(checks["bearer-auth-fail-closed"])
        self.assertTrue(checks["client-token-isolated"])
        self.assertTrue(checks["message-size-bound"])
        self.assertTrue(checks["parameter-depth-bound"])
        self.assertTrue(checks["logs-redacted"])
        self.assertTrue(checks["grounding-cache-isolated"])
        self.assertFalse(result["boundary"]["real_secrets_read"])
        self.assertEqual(result["boundary"]["token_source"], "generated-canary")
        self.assertEqual(result["canary_count"], len(CANARY_VALUES))
        for canary in CANARY_VALUES:
            self.assertNotIn(canary, serialized)


if __name__ == "__main__":
    unittest.main()
