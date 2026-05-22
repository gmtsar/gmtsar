"""conftest.py — pytest configuration for bin_py/tests.

Sets the pytest cache dir to a writable location so the PytestCacheWarning
about /home/.pytest_cache not being writable is suppressed when running via
a non-home-dir python installation (e.g. /home/staff/dliu/anaconda_knox).
"""
import os
import tempfile


def pytest_configure(config):
    """Redirect pytest cache to a per-process temp dir if the default is
    not writable.  The cache is only used for --lf / --stepwise; unit tests
    don't rely on it, so losing it between runs is safe."""
    default_cache = os.path.join(os.path.expanduser("~"), ".pytest_cache")
    if not os.access(os.path.dirname(default_cache) or "/", os.W_OK):
        # Override to a writable tmp dir.  pytest reads cache_dir from ini;
        # we can't set ini options at runtime, but we CAN set the env var
        # that pytest 7.x uses before the cache plugin initialises.
        os.environ.setdefault("PYTEST_CACHE_DIR",
                              os.path.join(tempfile.gettempdir(),
                                           f".pytest_cache_{os.getpid()}"))
