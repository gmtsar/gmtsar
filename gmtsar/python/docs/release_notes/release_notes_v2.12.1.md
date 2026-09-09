# v2.12.1 — WIN32 TIFF link fix now tagged; root README discoverability; tag-lineage note

Scope: HEAD `35ed088` (`origin/master` = `upstream/master`, PR #1125's
squash-merge) plus one uncommitted README change staged this session.
Patch release: no compute code touched, no sweep run (see below).

## What shipped

### 1. `gmtsar/CMakeLists.txt` WIN32 TIFF coalesce + fail-loud — already in HEAD, now tagged

Authored in a separate session as `4f7dcaa` and never tagged. `git diff
4f7dcaa HEAD -- gmtsar/CMakeLists.txt
gmtsar/python/bin_py/tests/test_windows_port.py` returns empty — the
exact content of that commit is present in `35ed088`, upstream's
squash-merge of PR #1125. This release is the first tag to carry it.

Fix: `find_package(TIFF REQUIRED)` reported success on a conda-forge
Windows install but left `TIFF_LIBRARY` empty, silently dropping TIFF
from `GMTSAR_LINK_LIBS`. Only `split_spectrum.exe` (the sole
`gmtsar/*.c` binary calling libtiff directly) failed, at link time,
hiding the root cause while 158 other targets built fine. The fix
coalesces `TIFF_LIBRARY` from `TIFF_LIBRARIES`, then a `find_library`
under a fresh cache var, then `FATAL_ERROR` at configure time if
nothing resolves. Regression guard: `test_cmake_win32_tiff_coalesce_
and_fail_loud` in `bin_py/tests/test_windows_port.py`, run and
confirmed PASSING this session (`22 passed, 1 skipped` in
`test_windows_port.py`; the one skip is `os.name != "nt"`-gated with
a stated reason, not silent).

**Not rewritten this session** — verified only, per this release's
scope. A deep audit (routed through `victor-reyes`) found the guard
has two real gaps, both left for a follow-up patch rather than touched
here (Rule: "verify it, don't rewrite it" for already-merged code):

- The `FATAL_ERROR` guard tests `NOT TIFF_LIBRARY` (emptiness), not
  validity. A stale/nonexistent path in the `TIFF_LIBRARY_WIN_FALLBACK`
  cache var, or a `TIFF_LIBRARY-NOTFOUND` token embedded in a list,
  reads as truthy and reaches the link line silently. Reachable via
  `install.py`'s own `--rebuild` flow, which reuses `build-win` without
  clearing `CMakeCache.txt`.
- `test_cmake_win32_tiff_coalesce_and_fail_loud` is four substring
  greps over the file text — it never invokes CMake. It would stay
  green through a guard inversion, a reordered branch, or the original
  bug (dropping `${TIFF_LIBRARY}` from the link line) recurring.

Both are tracked as open issues below, recommended for a v2.12.2
follow-up (the audit found `cmake -DCMAKE_SYSTEM_NAME=Windows` against
a `project(NONE)` stub runs sub-second on Linux, so an actual
CMake-configure regression test is buildable without a Windows host).

### 2. Root `README.md`: new INSTALL step 7 — Python framework discoverability

Previously the repo-root `README.md` had zero mention of
`gmtsar/python`, making the Python framework undiscoverable from the
top-level entry point. Added step 7 pointing at
`gmtsar/python/install.py` and `gmtsar/python/README.md`. Every claim
was checked against current source this session:

- The four `--system` choices (`ubuntu`, `conda`, `conda-linux-full`,
  `conda-windows-full`) — `install.py`'s `argparse` `choices=[...]`.
- `conda-windows-full` dispatches to `do_windows_build()`, which uses
  CMake/Ninja, not autoconf/configure/make.
- The installer builds in place (no separate install tree).
- `gmtsar/python/utils/` script names mirror the csh ones
  (`p2p_processing`, `pre_proc`, `geocode`, `intf`, `filter`, ... spot
  checked, all present).

**One factual bug found by the deep audit and fixed this session**: the
example command used `python3 gmtsar/python/install.py --system
conda-windows-full`. A fresh Anaconda Prompt on Windows has no
`python3` alias — `gmtsar/python/README.md:80-83` and the `v2.10.2`
release note both already document this exact gotcha (the `python3.exe`
shim is created *by* the install, not present before it). Fixed to
`python gmtsar/python/install.py --system conda-windows-full`. This is
the only wording change made to the new step 7 text; nothing else was
touched.

**Deferred, not fixed — flagged for the human before push**: the new
text says the framework is "verified bit-faithful over a 21-case
sweep." `gmtsar/python/README.md`'s own established phrasing for the
same claim is qualified — "verified bit-faithful ... across a 21-case
satellite matrix (20/21 clean; the one diff is the documented
Ridgecrest no-DEM corner)." The root README's summary sentence drops
that qualifier. Left as-is per this release's explicit instruction not
to edit the step-7 wording beyond the one factual command fix; recorded
here as an open item rather than silently corrected.

## Tag-lineage discontinuity: `v2.12.0` is not an ancestor of HEAD

`git merge-base --is-ancestor v2.12.0 HEAD` fails (exit 1). Root cause:
`v2.12.0` (tag object `aef5543`, pointing at commit `aa0aa0f`) was cut
on this fork's own linear history; upstream then squash-merged that
same branch (plus the subsequent `4f7dcaa` commit) as a single commit,
`35ed088` (PR #1125). Squash-merging discards the original commit
chain from `master`'s ancestry, so `aa0aa0f` is now an orphaned commit
— still reachable (the `v2.12.0` tag itself keeps it alive), but no
longer an ancestor of the branch tip.

**Verified this is a pure history rewrite, not a content divergence**:
`git diff aa0aa0f 35ed088 -- gmtsar/python` and `git diff aa0aa0f
35ed088 -- . ':!gmtsar/python'` both show exactly `4f7dcaa`'s two files
and nothing else — i.e. `35ed088`'s tree equals `aa0aa0f`'s tree plus
precisely the TIFF fix, with zero silent drift from the squash itself.

**Decision: leave the `v2.12.0` tag pointing at `aa0aa0f`, do not
retarget it.** Retargeting `v2.12.0` to `35ed088` would misrepresent
history — `35ed088` contains the TIFF fix, which `v2.12.0` never
shipped (that fix is what makes this `v2.12.1` release meaningful).
Moving a published, already-pushed annotated tag is also a rewrite of
public history this project's own convention (merge-not-rebase,
"don't rewrite history") argues against. The discontinuity is a
one-time artifact of the upstream squash-merge; this note is the
record of it. Going forward from `35ed088`, tag ancestry is linear
again (`v2.12.1` will correctly show as a descendant of `35ed088`).

## No sweep run — and why

Per project rule 5/15, a refactor or GMT-port change needs the full
21-case sweep before merge. Neither change in this release is one:
the CMake fix is a Windows-only build-configuration change (already
verified by its author on a real Windows link: "159/159" per the
`4f7dcaa` commit message), and the README change is documentation
only. No Python compute path, dispatcher, or test fixture changed.
The 21-case sweep (`tests/test_install.py --system conda --full`,
~3h) was **not run** for this release. What *was* run this session:
the full `bin_py/tests/test_windows_port.py` file (22 passed, 1
platform-gated skip) and a source-level re-verification of every
factual claim in the new README text (see above).

**Honest gap** (Rule 15): a README Installation-section change should
be verified by running the documented steps end-to-end. The exact
`--system conda-windows-full` command cannot be executed on this
Linux host at all, and this repo's own `test_install.py` has no
Windows automation. Verification here is source-inspection only
(`install.py` argparse, `do_windows_build`'s CMake/Ninja path,
`PATHWAY_FORWARD.md`'s existing "wired ON, clean-room proven for
RS2_SLC_Hawaii" record from `v2.10.x`–`v2.12.0`), plus the one
command-syntax bug the audit caught and this session fixed. No fresh
Windows clean-room run was performed.

## `PATHWAY_FORWARD.md`

Confirmed no update needed — no port, no wiring-state change landed
in this release.

## Deep audit (routed via `victor-reyes`)

Full findings list (haruto-nakamura, iris-vermeulen, sophia-okafor,
zofia-kaminska dispatched in parallel) — applied vs. deferred:

**Applied this session:**
- `README.md`: `python3` → `python` in the Windows install example
  (factual bug, verified against existing in-repo precedent).

**Deferred — open issues, need human judgment or a follow-up patch:**
- `gmtsar/CMakeLists.txt` TIFF guard: emptiness-only check, not a
  stale/invalid-path check (see above). Candidate v2.12.2 fix.
- `test_cmake_win32_tiff_coalesce_and_fail_loud`: text-grep only,
  doesn't invoke CMake, blind to 8 identified mutants (guard inversion,
  branch reorder, empty-coalesce, line-drop). Candidate v2.12.2 fix,
  routable to `iris-vermeulen`.
- No CI step runs `pytest` at all in this repo's GitHub Actions config
  — pre-existing gap, not introduced by this release, but means the
  new TIFF regression guard only fires on a manual run.
- Root `README.md`'s new step 7 softens/drops the `20/21` qualifier
  present in `gmtsar/python/README.md`'s own established phrasing for
  the same claim (see above) — left unedited per this release's scope,
  flagged for the human.
- **Rule-3 exception, both files**: `gmtsar/python/CLAUDE.md` states
  the fork's structural invariant as `git diff upstream/master..HEAD
  -- ':!gmtsar/python'` returning empty. This release's tree, and the
  working copy before this commit, both violate it —
  `gmtsar/CMakeLists.txt` (via `4f7dcaa`, already upstreamed into
  `35ed088`) and root `README.md` (this session) both live outside
  `gmtsar/python/`. The audit's read: the `CMakeLists.txt` divergence
  is discharged (it's real upstream C-build code, already accepted
  into `upstream/master` itself, not fork-only drift). The
  `README.md` divergence is real, open, fork-only drift — it exists
  only on `origin`, not `upstream`, and was added at explicit
  instruction this session as a deliberate discoverability decision,
  not proposed by this audit. **Surfaced here for the human's
  explicit sign-off before push** — the alternative is to upstream
  the README hunk as its own PR to `gmtsar/gmtsar` instead of carrying
  it as fork-only.
- `git add -A` would stage ~5,257 unrelated paths (`orbits/`,
  `gmt.history`, `preproc/*/include|lib`, etc., largely
  `install.py`-generated). Not done — this commit stages `README.md`
  only, by explicit path.

## Verification performed this session

- `git diff 4f7dcaa HEAD -- gmtsar/CMakeLists.txt
  gmtsar/python/bin_py/tests/test_windows_port.py` → empty (confirms
  the fix is already in HEAD).
- `python3 -m pytest gmtsar/python/bin_py/tests/test_windows_port.py -v`
  → 22 passed, 1 skipped (platform-gated, reason stated), 0 failed.
- Source re-verification of every root-`README.md` step-7 claim against
  `install.py`, `gmtsar/python/utils/`, `gmtsar/python/README.md`.
- Confirmed no `VERSION`/`__version__` string exists anywhere in this
  project to keep in sync — versioning lives entirely in git tags +
  `docs/release_notes/`.

### 3. `test_root_readme_is_pure_ascii` — regression guard for a real mojibake incident

Found the same day this release was cut: the fork's `v2.11.1` **GitHub
Release body** rendered as `Native Windows bundle 鈥??? supersedes...`.
Root cause: em-dashes written as UTF-8 (`E2 80 94`) sent through a
CP936/GBK-configured pipe from the Windows dev host, so `E2 80` decoded
as a CJK glyph and `94` became an unrecoverable replacement char. The
repo's own `.md` files were never corrupted — the damage happened in
transit to an external system.

Repaired all five occurrences in that release body (replaced with ASCII
`--` rather than restored `—`, so a mis-configured tool cannot re-mangle
them), and published the missing `v2.12.0`/`v2.12.1` release pages, which
had git tags but no GitHub Release object.

The new guard asserts the **root `README.md`** contains no byte > 0x7F.
That file is the highest-risk surface for this failure mode: it is
upstream's, it is read by everyone, and its text gets copied into release
announcements and issue replies where the mangling recurs. It was pure
ASCII before this project touched it and must stay that way.

Verified the guard actually fails: injected a real em-dash into the
README, confirmed `AssertionError: root README.md has 3 non-ASCII
byte(s), first at offset 1593 (0xE2)`, then restored the file
byte-exactly (`git diff --stat` empty). Full file: 17 passed in 0.67s.

Deliberately **not** applied to `docs/release_notes/` — that series uses
em-dashes and arrows throughout, is read through git/GitHub's own UTF-8
rendering, and has never been corrupted. Guarding it would be churn, not
safety.

## Files changed this release

- `README.md` (+11, 0 removed; includes the `python3`→`python` fix
  made this session).
- `gmtsar/python/bin_py/tests/test_install_config.py` (+31) — the
  `test_root_readme_is_pure_ascii` guard described above.
- `gmtsar/CMakeLists.txt`, `gmtsar/python/bin_py/tests/test_windows_port.py`
  — no new changes; already present in HEAD via `4f7dcaa`, now
  included under a tag for the first time.

## Assumptions

- "Patch" is the correct bump per this project's own scheme (bugfix +
  doc change, no new capability, no full sweep) — `v2.12.0` → `v2.12.1`.
- The `v2.12.0` tag's target commit (`aa0aa0f`) remains valid as
  historical record even though it is no longer an ancestor of
  `master`; it is not deleted or moved, per this project's "never
  delete/rewrite a prior release" discipline extended to tags.
