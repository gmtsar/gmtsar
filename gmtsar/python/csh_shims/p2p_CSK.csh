#!/bin/csh -f
# Deprecated wrapper shim — forwards to p2p_processing.csh SAT ... so that
# legacy tarball READMEs (topex.ucsd.edu/gmtsar/tar/) keep working.
# These per-SAT wrappers were superseded by p2p_processing.csh's SAT-dispatch
# years ago, but some bundled READMEs still call them.
exec p2p_processing.csh CSK_RAW $argv
