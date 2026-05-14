#! /usr/bin/env python3
"""Freeze a copy of csh run outputs from work/csh_test/ into tests/reference/
so compare.py can validate against a known-good baseline without re-running
the slow csh recipe.

Usage:  python3 freeze_reference.py [--force]

Copies the comparison-target files from
<workdir>/csh_test/<case>/<intf>/<file>  →  tests/reference/<case>/<intf>/<file>
where <intf> is auto-discovered from the filesystem (any subdir containing
corr_ll.grd). Skips files that already exist in reference/ unless --force.
"""
import argparse, glob, os, shutil
from cases import caseNameList, cshRefRoot
from compare import fileNameList

REF_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference')
CSH_ROOT = cshRefRoot.rstrip(os.sep)


def discover_intf_dirs(case):
    """Subdirs of csh_test/<case>/ that contain AT LEAST ONE comparison-target
    file. S1_TOPS subswath dirs and merge/ produce disjoint subsets, so a
    single-file sentinel would miss half of them."""
    case_root = f'{CSH_ROOT}/{case}'
    if not os.path.isdir(case_root):
        return []
    dirs = set()
    for fname in fileNameList:
        for p in glob.glob(f'{case_root}/**/{fname}', recursive=True):
            dirs.add(os.path.dirname(os.path.relpath(p, case_root)))
    return sorted(dirs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--force', action='store_true', help='overwrite existing reference files')
    ap.add_argument('--cases', help='comma-separated subset of cases (default: all)')
    args = ap.parse_args()
    cases = args.cases.split(',') if args.cases else caseNameList

    copied = skipped = missing = 0
    for case in cases:
        for intf in discover_intf_dirs(case):
            for fname in fileNameList:
                src = os.path.join(CSH_ROOT, case, intf, fname)
                dst = os.path.join(REF_DIR, case, intf, fname)
                if not os.path.isfile(src):
                    missing += 1
                    continue
                if os.path.isfile(dst) and not args.force:
                    skipped += 1
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
                print(f'froze {case}/{intf}/{fname}')

    print(f'\n{copied} copied, {skipped} already present, {missing} missing in csh_test/')
    print(f'reference dir: {REF_DIR}')


if __name__ == '__main__':
    main()
