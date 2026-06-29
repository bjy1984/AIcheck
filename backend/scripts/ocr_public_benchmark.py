from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.ocr_service.public_benchmarks import (
    PUBLIC_BENCHMARK_DATASETS,
    build_public_benchmark_index,
    public_dataset_registry,
)
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Index public OCR foundation benchmark datasets for AIcheck.")
    parser.add_argument("--list-datasets", action="store_true", help="Print supported public benchmark datasets.")
    parser.add_argument("--dataset", choices=sorted(PUBLIC_BENCHMARK_DATASETS), help="Dataset key to index.")
    parser.add_argument("--dataset-root", help="Local dataset root. Public data must be downloaded outside production.")
    parser.add_argument("--split", help="Optional dataset split hint, such as train, val, test, or test-a.")
    parser.add_argument("--limit", type=int, help="Maximum cases to index for a mini benchmark.")
    parser.add_argument("--output", help="Benchmark report JSON output path.")
    parser.add_argument("--case-output", help="Optional eval-case style JSON output path.")
    args = parser.parse_args()

    if args.list_datasets:
        print(json.dumps(public_dataset_registry(), ensure_ascii=False, indent=2))
        return 0
    if not args.dataset or not args.dataset_root:
        parser.error("--dataset and --dataset-root are required unless --list-datasets is used")

    report = build_public_benchmark_index(
        args.dataset,
        Path(args.dataset_root),
        limit=args.limit,
        split=args.split,
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    if args.case_output:
        write_text_file(
            Path(args.case_output),
            json.dumps(
                {
                    "schemaVersion": "aicheck-ocr-public-benchmark-cases-v1",
                    "name": f"{report['dataset']}_foundation_benchmark",
                    "foundationBenchmark": True,
                    "productionCertificationEligible": False,
                    "cases": report["cases"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    print(json.dumps({key: report[key] for key in ["dataset", "ok", "summary", "blockers"]}, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
