"""Regression checks for clean-host isolation and existing-volume protection."""

import argparse
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import control


class ControlIsolationTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_clean_host_can_use_an_empty_protected_baseline(self):
        with patch.object(control, "call", return_value=""):
            self.assertEqual(control.inventory(), [])

    @patch.dict(os.environ, {"ATLAS_E2E_PROTECTED_PROJECT": "reviewed-site"}, clear=True)
    def test_missing_explicit_protected_project_fails(self):
        with patch.object(control, "call", return_value="") as call:
            with self.assertRaisesRegex(RuntimeError, "five protected"):
                control.inventory()
            self.assertIn("label=com.docker.compose.project=reviewed-site", call.call_args.args)

    @patch.dict(os.environ, {}, clear=True)
    def test_incomplete_existing_local_stack_fails(self):
        with patch.object(control, "call", return_value="container-a\ncontainer-b\n"):
            with self.assertRaisesRegex(RuntimeError, "five protected"):
                control.inventory()

    def test_existing_volume_is_rejected_before_creating_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-run"
            project = "atlas-e2e-existing-volume"
            args = argparse.Namespace(run_id="e2e-existing-volume")
            with patch.object(control, "paths", return_value=(output, project)):
                with patch.object(control, "call", side_effect=["", project + "_e2e-data\n"]):
                    with self.assertRaisesRegex(RuntimeError, "volume identity"):
                        control.start(args)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
