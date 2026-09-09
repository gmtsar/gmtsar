# v2.10.2 — clean-room hardening for `--system conda-windows-full` + Rule-8 regression guards

Scope: `v2.10.1..v2.10.2`. Two real bugs found by the first genuinely
clean-room Windows run (fresh clone AND fresh conda env — v2.10.0's own
verification had reused a pre-existing env, masking both), plus the
regression tests and ledger updates Rules 8/13 required before this tag.

## Real bug: fresh-env `conda create` failed in milliseconds (cmd metacharacters)

`_windows_conda_cmd()` routed conda through `cmd /c conda.bat`. cmd
PARSES the command line, so the package spec `libtiff>=4.5,<5` was read
as redirection operators (stdin from a file named `5`) — "The system
cannot find the file specified" in 0.026s. Unfixable by quoting from a
subprocess argv list (`list2cmdline` escapes embedded quotes as `\"`,
which survive the `.bat`'s `%*` forwarding as literal quote characters
in conda's argv — verified, not assumed).

**Fix** (`7dd6880`): prefer `Scripts\conda.exe` — a real PE executable,
no cmd, no metacharacter parsing. Tested standalone-working on conda
26.5.3 (`create`, `env list --json`), disproving the earlier docstring
claim that it "only works once the env is active". The `.bat`+cmd route
survives only as a fallback for installs with no `Scripts\conda.exe`,
and now fails loudly on metacharacter args instead of letting cmd
misparse them.

## Real bug: `pip` missing from `WINDOWS_CONDA_BOOTSTRAP_PACKAGES`

Identical bug class to the one v2.9.0 fixed in
`CONDA_FORGE_BOOTSTRAP_PACKAGES`: python arrives transitively
(gmt → gdal → python bindings) but pip is not guaranteed to, and
`do_python_deps` runs `python.exe -m pip install -r requirements.txt`.
Fixed preemptively (`1be3bce`) citing the v2.9.0 precedent, then
confirmed exercised for real: the fresh `gmtsar_cr` env's pip step ran
clean (204.8s, rc=0).

## Clean-room verification (Rules 14/15, the real thing this time)

Fresh folder + fresh clone (`D:\gmtsar-cleanroom2`, HEAD `7dd6880`,
clean tree) + genuinely new conda env (`gmtsar_cr`, never existed);
only the RS2 tarball cache reused, per Rule 14. Results:

- `install.py --system conda-windows-full --conda-env gmtsar_cr`:
  from-scratch `conda create` rc=0 in 196.9s via `Scripts\conda.exe`
  with the metachar spec intact; pip rc=0; CMake/Ninja build → 38
  exes; both `c_fixes` (conv.c "rb", fitoffset.c strlcpy) auto-applied.
  (Caveat, stated per Rule 4: one launch was killed mid-CMake-configure
  after env creation had succeeded; the relaunch resumed idempotently.
  Every stage has fresh rc=0 evidence in `install_logs/`.)
- `sweep.py --fast --cases RS2_SLC_Hawaii --topo-mode-ab`: **6/6
  comparisons SUCCESS** (compare.py's own thresholds) — SSIM ≥0.999
  ×3, `corr_ll.grd` RMS 4.1e-4, `filtcorr.grd` 6.6e-4, `phasefilt.grd`
  complex-RMS 0.0109. mode0 405s / mode1 380s (1.07×). Visual
  comparison generated via `tools/py_vs_csh_figure.py` (AB trees
  bridged read-only via directory junctions): full-swath fringes both
  sides, indistinguishable by eye, matching the same-commit Linux
  py-vs-csh reference.

## Rule-8 debt paid: `bin_py/tests/test_windows_port.py` (NEW, 15 guards)

One regression test per real bug from the v2.10.x bring-up: cmd
metacharacter handling + conda.exe preference + `.bat`-fallback
fail-loud; pip in the Windows bootstrap list; `_apply_c_fixes` wired
into `do_windows_build`; conv.c staged/wired/binary-mode (all three
layers); `_win_bash` env override, System32-WSL-stub rejection, and a
16-thread no-caller-sees-None race guard; `resolve_sharedir`
forward-slash contract; `case_runner` PATH via `os.pathsep`; `cases.py`
tree-name derivation under both `TOPO_MODE_AB` settings (the
directory-collapse bug); `_run_recipe` resolving bash via `_win_bash`.
All static/mock/tiny-fixture — they run and pass on POSIX too.

Plus one fix to a pre-existing test: `test_pytest_in_requirements_txt`
read `requirements.txt` with the locale codepage (GBK on this host) and
crashed on the file's UTF-8 content — encoding now pinned. 27/27 pass
on the Windows dev host.

## Docs (Rule 13 debt paid)

- `PATHWAY_FORWARD.md`: new top entry for the Windows port — wired-ON
  state, clean-room evidence, the conv.c upstream bug, and the honest
  gaps (no csh on Windows ever; only RS2 exercised; `distribute_
  gmtsar_windows.py` `--verify` currently FAILING at 27/38 exes and
  must not ship until it passes on a bare machine).
- `README.md`: the Windows install command is `python`, not `python3`
  (an Anaconda Prompt has no `python3` alias — the shim only exists
  inside the env AFTER install; bit the clean-room walkthrough for
  real).
