#!/usr/bin/env python3
"""test_sha_tracking — verify git-SHA tracking in case_runner.sh + compare.py.

Why this test exists
--------------------
Sweeps take 30 minutes to 3 hours. A Mira completing mid-sweep wants to
commit. If the framework changes between case-1 and case-21, the later
cases ran against different code than the earlier ones, and the
scorecard's pass/fail mixes results across versions. That makes a
"PASS" attributable to no single SHA — which is exactly the failure mode
we hit in v1.12.0 (Wei session log 2026-05-22).

Detection design (this test guards items 1-4 of the design):

  1. case_runner.sh records HEAD + dirty file list at case start →
     <workdir>/results/<case>.git_sidecar
  2. Re-reads HEAD + dirty list at case end → appends to sidecar.
  3. compare.py reads sidecar, embeds into per-case JSON:
       git_sha, git_dirty, dirty_files, launched_at, finished_at,
       sha_at_end, vintage_warnings: [...]
  4. If HEAD advanced mid-case → warning 'MIXED_VINTAGE_SHA_CHANGE'.
     If dirty file set changed mid-case → 'MIXED_VINTAGE_DIRTY'.

The test synthesises a tiny throwaway git repo (so we don't depend on
the real fork's git state — that would make the test order-dependent
and fragile under CI worktrees), simulates a mid-case commit, and
asserts the sidecar + compare.py output reflect the change.

We do NOT run the full case_runner.sh pipeline (that would need a real
SAR tarball + gmt + p2p binaries). We invoke case_runner.sh-style SHA
capture as a thin shell snippet — same `git rev-parse HEAD` + sidecar
write logic — then call compare.py's `_read_git_sidecar` helper
directly to verify the JSON fields and the warning marker.

Per project_rules.md #11: a regression test must accompany this
infrastructure so the SHA-tracking code can't silently break.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_TESTS_DIR = _HERE.parent.parent / "tests"   # gmtsar/python/tests
_COMPARE_PY = _TESTS_DIR / "compare.py"
_CASE_RUNNER = _TESTS_DIR / "case_runner.sh"


def _git(repo: Path, *argv: str, check=True) -> str:
    """Run a git command in `repo`, return stripped stdout."""
    out = subprocess.run(
        ["git", "-C", str(repo), *argv],
        check=check, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _init_repo(repo: Path) -> str:
    """Create a tiny git repo with one commit. Returns the HEAD SHA."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name",  "Test")
    # Mimic the repo layout case_runner.sh assumes — it walks
    # `dirname/$0/../../..` to find the repo root, and limits the
    # dirty-files probe to `gmtsar/python/`.
    (repo / "gmtsar" / "python").mkdir(parents=True, exist_ok=True)
    (repo / "gmtsar" / "python" / "anchor.py").write_text("x = 1\n")
    _git(repo, "add", "gmtsar/python/anchor.py")
    _git(repo, "commit", "-q", "-m", "initial")
    return _git(repo, "rev-parse", "HEAD")


def _write_sidecar(results_dir: Path, case: str, *,
                   sha_start: str, sha_end: str,
                   dirty_start: str = "", dirty_end: str = "",
                   launched: str = "2026-05-22T12:00:00Z",
                   finished: str = "2026-05-22T12:30:00Z") -> Path:
    """Write a .git_sidecar with the exact format case_runner.sh emits.

    Kept in lockstep with the heredoc in case_runner.sh — if that
    layout changes, this test must change too.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{case}.git_sidecar"
    path.write_text(
        f"# git-sha sidecar — synthetic for test\n"
        f"case={case}\n"
        f"launched_at={launched}\n"
        f"sha_at_start={sha_start}\n"
        f"dirty_files_at_start={dirty_start}\n"
        f"finished_at={finished}\n"
        f"sha_at_end={sha_end}\n"
        f"dirty_files_at_end={dirty_end}\n"
    )
    return path


def _load_compare_helpers(results_dir: Path):
    """Import compare.py's `_read_git_sidecar` with RESULTS_DIR pointing
    at our fixture directory.

    compare.py is module-level executable code that walks every case in
    caseNameList. We can't `import` it without it doing the full
    comparison pass. So we splice in just the helper function via a
    fresh module that defines RESULTS_DIR + the helper.
    """
    src = _COMPARE_PY.read_text()
    # Extract the helper function. We rely on the function name being
    # unique in the file and being followed by the comparison loop.
    start = src.index("def _read_git_sidecar(")
    end = src.index("\n\n", start)
    while src[end:end+5] == "\n\n   ":   # body continuation
        end = src.index("\n\n", end + 1)
    helper_src = src[start:end]
    ns = {
        "os":   __import__("os"),
        "RESULTS_DIR": str(results_dir),
    }
    exec(helper_src, ns)
    return ns["_read_git_sidecar"]


class TestSidecarSchema(unittest.TestCase):
    """compare.py's _read_git_sidecar contract — happy path + warnings."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sha_track_"))
        self.results = self.tmp / "results"
        self.results.mkdir()
        self._read = _load_compare_helpers(self.results)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_run_no_warnings(self):
        """Same SHA at start and end, no dirty files → no warnings."""
        _write_sidecar(
            self.results, "Clean_Case",
            sha_start="abcdef0123456789",
            sha_end  ="abcdef0123456789",
        )
        out = self._read("Clean_Case")
        self.assertEqual(out["git_sha"], "abcdef0")
        self.assertEqual(out["sha_at_end"], "abcdef0")
        self.assertFalse(out["git_dirty"])
        self.assertEqual(out["dirty_files"], [])
        self.assertEqual(out["vintage_warnings"], [])
        # Sidecar should be consumed (deleted) after read.
        self.assertFalse((self.results / "Clean_Case.git_sidecar").exists())

    def test_mid_case_sha_change_flagged(self):
        """HEAD advances during the case → MIXED_VINTAGE_SHA_CHANGE."""
        _write_sidecar(
            self.results, "Mid_Commit_Case",
            sha_start="aaaaaaa1111111111111111111111111111111",
            sha_end  ="bbbbbbb2222222222222222222222222222222",
        )
        out = self._read("Mid_Commit_Case")
        self.assertEqual(out["git_sha"], "aaaaaaa")
        self.assertEqual(out["sha_at_end"], "bbbbbbb")
        # The warning must fire with both short SHAs.
        joined = " ".join(out["vintage_warnings"])
        self.assertIn("MIXED_VINTAGE_SHA_CHANGE", joined)
        self.assertIn("aaaaaaa", joined)
        self.assertIn("bbbbbbb", joined)

    def test_dirty_set_change_flagged(self):
        """Dirty file set changes mid-case → MIXED_VINTAGE_DIRTY."""
        _write_sidecar(
            self.results, "Dirty_Case",
            sha_start="0" * 40, sha_end="0" * 40,
            dirty_start="gmtsar/python/utils/foo.py",
            dirty_end  ="gmtsar/python/utils/foo.py,gmtsar/python/utils/bar.py",
        )
        out = self._read("Dirty_Case")
        # No SHA change, but the dirty set grew during the case.
        joined = " ".join(out["vintage_warnings"])
        self.assertNotIn("MIXED_VINTAGE_SHA_CHANGE", joined)
        self.assertIn("MIXED_VINTAGE_DIRTY", joined)
        self.assertIn("bar.py", joined)
        # The 'dirty_files' field surfaces the START set in the JSON.
        self.assertEqual(out["dirty_files"], ["gmtsar/python/utils/foo.py"])
        self.assertTrue(out["git_dirty"])

    def test_missing_sidecar_returns_empty_record(self):
        """Legacy run (no sidecar) → empty record, no exceptions.

        Required by the mission constraint: 'old per-case JSONs must
        still parse — just with optional new fields'.
        """
        out = self._read("Legacy_Case")
        self.assertEqual(out["git_sha"], "")
        self.assertEqual(out["dirty_files"], [])
        self.assertEqual(out["vintage_warnings"], [])

    def test_malformed_sidecar_does_not_crash(self):
        """Garbled sidecar → still returns dict, possibly with a
        sidecar_read_error warning, never raises."""
        path = self.results / "Garbled_Case.git_sidecar"
        # Write a few key=value lines mixed with junk that the parser
        # must tolerate (blank lines, lines without '=', '#' comments).
        path.write_text(
            "# comment line\n"
            "\n"
            "sha_at_start=abc1234\n"
            "this is not a key=value pair\n"
            "sha_at_end=abc1234\n"
        )
        out = self._read("Garbled_Case")
        # SHA fields populated from the valid lines.
        self.assertEqual(out["git_sha"], "abc1234")
        self.assertEqual(out["sha_at_end"], "abc1234")


class TestCaseRunnerSidecarEndToEnd(unittest.TestCase):
    """Black-box test: run a stripped case_runner-style SHA capture in a
    real git repo, simulate a mid-case commit, and verify the helper sees
    MIXED_VINTAGE_SHA_CHANGE.

    We do NOT execute the real case_runner.sh — that needs SAR data,
    gmt, the csh pipeline, ~5-30 min wall time, and would write
    sidecars without simulating the mid-case commit. Instead we run the
    exact SHA-capture snippet from case_runner.sh against a throwaway
    git repo.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sha_track_e2e_"))
        self.repo = self.tmp / "fork"
        self.head0 = _init_repo(self.repo)
        # case_runner.sh expects pyDir at <workdir>/python_test/<case>;
        # the sidecar lands at <workdir>/results/<case>.git_sidecar.
        self.workdir = self.tmp / "work"
        self.pydir = self.workdir / "python_test" / "Synthetic_Case"
        self.pydir.mkdir(parents=True)
        self.results = self.workdir / "results"
        self.results.mkdir()
        self._read = _load_compare_helpers(self.results)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _capture_start(self, case: str) -> Path:
        """Replicate case_runner.sh's start-of-case capture block.

        Kept literal to surface drift between this test and the shell:
        if case_runner.sh changes its sidecar layout, this snippet (and
        the assertions below) must change in the same commit.
        """
        script = f"""set -u
case={case}
pyDir={self.pydir}
_repo_root_for_sha="$(cd {self.repo} && git rev-parse --show-toplevel)"
sha_at_case_start="$(cd "$_repo_root_for_sha" && git rev-parse HEAD)"
dirty_files_at_case_start="$(cd "$_repo_root_for_sha" && git diff --name-only HEAD -- gmtsar/python/ | tr '\\n' ',' | sed 's/,$//')"
case_launched_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
_results_dir="$(dirname "$(dirname "$pyDir")")/results"
mkdir -p "$_results_dir"
_sidecar="$_results_dir/${{case}}.git_sidecar"
cat > "$_sidecar" <<EOF
case=$case
launched_at=$case_launched_at
sha_at_start=$sha_at_case_start
dirty_files_at_start=$dirty_files_at_case_start
EOF
echo "$_sidecar"
"""
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())

    def _capture_end(self, sidecar: Path):
        """Replicate case_runner.sh's end-of-case capture block."""
        script = f"""set -u
_sidecar={sidecar}
_repo_root_for_sha="$(cd {self.repo} && git rev-parse --show-toplevel)"
sha_at_case_end="$(cd "$_repo_root_for_sha" && git rev-parse HEAD)"
dirty_files_at_case_end="$(cd "$_repo_root_for_sha" && git diff --name-only HEAD -- gmtsar/python/ | tr '\\n' ',' | sed 's/,$//')"
case_finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat >> "$_sidecar" <<EOF
finished_at=$case_finished_at
sha_at_end=$sha_at_case_end
dirty_files_at_end=$dirty_files_at_case_end
EOF
"""
        subprocess.run(["bash", "-c", script], check=True, capture_output=True)

    def test_mid_case_commit_triggers_warning(self):
        """The headline test: synthesize a mid-case commit and verify the
        compare.py helper flags MIXED_VINTAGE_SHA_CHANGE."""
        sidecar = self._capture_start("Synthetic_Case")
        self.assertTrue(sidecar.exists())

        # ── Simulate the failure scenario: a commit lands while the
        # case is running. (In a real sweep this would be a Mira
        # finishing her work and committing.)
        (self.repo / "gmtsar" / "python" / "new_file.py").write_text("y = 2\n")
        _git(self.repo, "add", "gmtsar/python/new_file.py")
        _git(self.repo, "commit", "-q", "-m", "feat: mid-case commit")
        head1 = _git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(self.head0, head1, "git_commit didn't advance HEAD")

        self._capture_end(sidecar)
        # Sidecar now has BOTH start (head0) and end (head1) lines.

        out = self._read("Synthetic_Case")
        self.assertEqual(out["git_sha"],     self.head0[:7])
        self.assertEqual(out["sha_at_end"],  head1[:7])
        joined = " ".join(out["vintage_warnings"])
        self.assertIn("MIXED_VINTAGE_SHA_CHANGE", joined,
                      f"expected MIXED_VINTAGE_SHA_CHANGE in: {joined!r}")

    def test_clean_case_no_commit_no_warning(self):
        """Negative control: no mid-case commit → no warning."""
        sidecar = self._capture_start("Clean_Synthetic")
        self._capture_end(sidecar)
        out = self._read("Clean_Synthetic")
        self.assertEqual(out["git_sha"], self.head0[:7])
        self.assertEqual(out["sha_at_end"], self.head0[:7])
        self.assertEqual(out["vintage_warnings"], [],
                         f"unexpected warnings on clean run: {out['vintage_warnings']}")

    def test_mid_case_uncommitted_edit_triggers_dirty_warning(self):
        """Working-tree mutation (no commit) → MIXED_VINTAGE_DIRTY."""
        sidecar = self._capture_start("Edit_Synthetic")
        # Touch a tracked file under gmtsar/python/ so `git diff
        # --name-only HEAD -- gmtsar/python/` lists it.
        anchor = self.repo / "gmtsar" / "python" / "anchor.py"
        anchor.write_text(anchor.read_text() + "# touched mid-case\n")
        self._capture_end(sidecar)
        out = self._read("Edit_Synthetic")
        joined = " ".join(out["vintage_warnings"])
        # No SHA advance, but dirty set went 0 → 1.
        self.assertNotIn("MIXED_VINTAGE_SHA_CHANGE", joined)
        self.assertIn("MIXED_VINTAGE_DIRTY", joined,
                      f"expected MIXED_VINTAGE_DIRTY in: {joined!r}")


if __name__ == "__main__":
    unittest.main()
