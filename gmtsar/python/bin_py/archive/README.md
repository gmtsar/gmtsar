# Archive — superseded ports, kept for reference only

Files here are **not on PATH**, not imported by anything, and not the
baseline. They exist because they represent real, documented work that
might be revisited later — not because they're still viable defaults.

## `resamp_py_v2`

Archived 2026-07-12. Was briefly the wired `resamp_py` default (via a
`bin/resamp_py` symlink) but its numba on-disk JIT cache defaults to
`bin_py/__pycache__`, which lives on NFS — synchronous NFS stat/open
round-trips during cache validation made wall time unstable (10-58s on
identical input). Plain `resamp_py` (now the wired baseline, see
`gmtsar/python/bin_py/resamp_py`) is byte-identical to C and a consistent
~1.3x faster, with no such instability.

If this design is ever revisited (e.g. to recover v2's theoretical
warm-cache advantage), point `NUMBA_CACHE_DIR` at local disk before
re-measuring — see `gmtsar/python/docs/PATHWAY_FORWARD.md` "resamp_py /
xcorr_py, resolved 2026-07-12" for the full measurement.

**Do not symlink this back onto PATH as `resamp_py` without re-verifying
the NFS-cache fix first.**
