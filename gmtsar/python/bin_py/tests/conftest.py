"""conftest.py — pytest configuration for bin_py/tests.

Sets the pytest cache dir to a writable location so the PytestCacheWarning
about /home/.pytest_cache not being writable is suppressed when running via
a non-home-dir python installation (e.g. /home/staff/dliu/anaconda_knox).

Also probes a short list of common install locations for `gmt` (and this
fork's own build output dir) and extends PATH for the test session if the
binary isn't already resolvable -- see _extend_path_for_known_tools below.
"""
import os
import shutil
import tempfile


# bin_py/tests/ unit/parity tests each do their own `shutil.which("gmt")`
# skip-check (by design -- Rule 1 wants a loud, specific skip reason, not a
# silent pass). But most of them don't fall back to checking common conda
# locations if a bare shell hasn't sourced/activated an env, so a huge
# fraction of skips are just "forgot to activate the env" rather than "gmt
# genuinely isn't installed". This is a one-time, printed PATH *extension*
# (not a behavioral fallback masking a failure): if none of these paths pan
# out either, PATH is left untouched and every test's own skip-check still
# fires with its existing, specific message -- nothing here silently changes
# what a test decides or hides a real absence of gmt.
_COMMON_TOOL_DIRS = [
    "/home/staff/dliu/anaconda3/envs/gmtsar/bin",     # this project's known dev host env
    os.path.expanduser("~/anaconda3/envs/gmtsar/bin"),
    os.path.expanduser("~/miniconda3/envs/gmtsar/bin"),
    "/opt/conda/envs/gmtsar/bin",
    "/home/utig5/dliu/gmtsar/bin",                     # this fork's own `install.sh --build` output
]


def _extend_path_for_known_tools():
    if shutil.which("gmt"):
        return
    for d in _COMMON_TOOL_DIRS:
        if os.path.isfile(os.path.join(d, "gmt")):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            print(f"[conftest] gmt not on PATH; found at {d}, "
                  "prepending to PATH for this test session.")
            return
    print("[conftest] gmt not on PATH and not found in any known common "
          "location; parity tests needing it will skip with their own "
          "reason.")


_extend_path_for_known_tools()


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
