#!/usr/bin/env python3
"""Mirror DAB benchmark queries into our local `runs/` tree.

For every `/DataAgentBench/query_<dataset>/query<N>/` we copy:
  - query.json
  - ground_truth.csv
  - validate.py

into `runs/<dataset>/query<N>/`, preserving DAB's folder conventions so the
scoring script can dynamically import each query's validate.py.

Usage:
    python scripts/scaffold_bench.py                  # all datasets, all queries
    python scripts/scaffold_bench.py --dataset agnews # one dataset
    python scripts/scaffold_bench.py --force          # overwrite existing files
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REQUIRED_FILES = ("query.json", "ground_truth.csv", "validate.py")
DAB_ROOT = Path("/DataAgentBench")
RUNS_ROOT = Path(__file__).resolve().parent.parent / "runs"


def _dataset_name(query_dir: Path) -> str:
    # /DataAgentBench/query_agnews -> agnews
    return query_dir.name[len("query_"):].lower()


def scaffold(dataset: str | None, force: bool) -> int:
    if not DAB_ROOT.is_dir():
        sys.exit(f"DAB root not found: {DAB_ROOT}")

    dataset_dirs = sorted(DAB_ROOT.glob("query_*"))
    if dataset:
        dataset_dirs = [d for d in dataset_dirs if _dataset_name(d) == dataset.lower()]
        if not dataset_dirs:
            sys.exit(f"No DAB directory matches dataset '{dataset}'.")

    copied = skipped = 0
    for ds_dir in dataset_dirs:
        ds_name = _dataset_name(ds_dir)
        for query_dir in sorted(ds_dir.glob("query*")):
            if not query_dir.is_dir() or query_dir.name == "query_dataset":
                continue
            if not all((query_dir / f).exists() for f in REQUIRED_FILES):
                continue

            target = RUNS_ROOT / ds_name / query_dir.name
            target.mkdir(parents=True, exist_ok=True)

            for fname in REQUIRED_FILES:
                dst = target / fname
                if dst.exists() and not force:
                    skipped += 1
                    continue
                shutil.copy2(query_dir / fname, dst)
                copied += 1

            print(f"  {ds_name}/{query_dir.name}  ← {query_dir}")

    print(f"\nDone. copied={copied} skipped={skipped} (use --force to overwrite)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", help="Only scaffold this dataset (e.g. agnews).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    args = parser.parse_args()
    return scaffold(args.dataset, args.force)


if __name__ == "__main__":
    sys.exit(main())
