"""All API tests run against a disposable database, never a personal workspace."""

import atexit
import os
import tempfile

test_data = tempfile.TemporaryDirectory(prefix="atlas-backend-tests-")
os.environ["ATLAS_DATA_DIR"] = test_data.name
# Historical API tests explicitly exercise the retained legacy deployment mode.
# Browser-mode tests override these flags and assert the production default.
os.environ["ATLAS_COMPUTE_MODE"] = "legacy"
os.environ["ATLAS_CLOUD_PROOF_GENERATION"] = "true"
atexit.register(test_data.cleanup)
