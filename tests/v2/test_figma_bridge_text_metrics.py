from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


class FigmaBridgeTextMetricsTests(unittest.TestCase):
    def test_bridge_plugin_serializes_async_actions(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_plugin_action_queue.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge plugin queue test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("plugin actions serialized", result.stdout)

    def test_bridge_edit_batch_rolls_back_all_successful_edits(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_edit_batch_rollback.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge edit batch rollback test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("edit batch rollback completed", result.stdout)

    def test_bridge_applies_grid_and_wrap_layout(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_grid_wrap_layout.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge grid/wrap layout test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("grid and wrap layout completed", result.stdout)

    def test_bridge_layout_transaction_restores_frame_and_children(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_layout_transaction_rollback.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge layout transaction rollback test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("layout transaction rollback completed", result.stdout)

    def test_bridge_component_instance_override_is_isolated(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_component_instance_probe.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge component instance test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("component instance probe completed", result.stdout)

    def test_bridge_rejects_unsupported_layout_mode(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_layout_mode_fail_closed.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge layout mode test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("unsupported layout mode failed closed", result.stdout)

    def test_bridge_batch_rolls_back_created_nodes(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_batch_rollback.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge batch rollback test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("batch rollback completed", result.stdout)

    def test_bridge_marks_owned_nodes_and_cleans_exact_job(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_ownership_marker_cleanup.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge ownership marker test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn(
            "ownership marker and job cleanup completed",
            result.stdout,
        )

    def test_bridge_fails_closed_for_missing_parent(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_parent_missing_fail_closed.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge parent fail-closed test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("missing parent failed closed", result.stdout)

    def test_bridge_echoes_request_id(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_request_id_echo.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge request id test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("requestId echoed", result.stdout)

    def test_bridge_resolves_variable_named_instances(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = (
            repo_root / "tests" / "bridge" / "test_variable_font_named_instances.js"
        )
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge variable font test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("variable named instances resolved", result.stdout)

    def test_bridge_resolves_italic_font_faces(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_italic_font_style.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge italic font test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("italic font style resolved", result.stdout)

    def test_multiline_overflow_keeps_top_edge(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_multiline_overflow_position.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge multiline overflow test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("multiline overflow keeps top edge", result.stdout)

    def test_bridge_applies_frame_background_color(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_frame_background.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge frame background test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("frame backgroundColor applied", result.stdout)

    def test_bridge_applies_explicit_line_height_to_single_line_text(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("node is required for the Figma bridge behavior test")

        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "tests" / "bridge" / "test_text_line_height.js"
        result = subprocess.run(
            [node, str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            "Figma bridge text metrics test failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("single-line text lineHeight applied", result.stdout)


if __name__ == "__main__":
    unittest.main()
