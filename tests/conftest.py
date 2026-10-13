"""Test configuration: force offline mode and a throwaway database BEFORE any app import.

This runs at collection time, before test modules are imported, so `app.config` (which reads
`.env` at import) always sees the mock provider and a temporary database. Without this, adding a
second test module that imports `app.coach` at module level would make live API calls and write to
the real `glpal.db`.
"""
import os
import tempfile


def pytest_configure(config):
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["GLPAL_DB"] = os.path.join(tempfile.mkdtemp(prefix="glpal-test-"), "test.db")
