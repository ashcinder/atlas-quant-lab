"""All API tests run against a disposable database, never a personal workspace."""

import atexit
import os
import tempfile

test_data = tempfile.TemporaryDirectory(prefix="atlas-backend-tests-")
os.environ["ATLAS_DATA_DIR"] = test_data.name
atexit.register(test_data.cleanup)
