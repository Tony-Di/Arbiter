"""Build a reproducible Civil Comments sample and human-annotation template.

Run from the repository root, after installing Hugging Face ``datasets``:
    python scripts/build_system_eval.py --safe 30 --gray 70 --harmful 30
    python scripts/build_system_eval.py --mode high-risk
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from arbiter.eval.system_data import (
    DATASET_ID,
    DATASET_SPLIT,
    GRAY_MAX,
    GRAY_MIN,
    HARMFUL_MIN,
    IDENTITY_HATE_MIN,
    SAFE_MAX,
    SEVERE_TOXIC_MIN,
    THREAT_MIN,
    sample_civil_comments,
    sample_high_risk_civil_comments,
    write_candidate_files,
)


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _unit_interval_float(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def _candidate_ids(path: Path) -> set[str]:
    if not path.is_file():
        raise SystemExit(f"exclude candidate file does not exist: {path}")
    ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                payload = json.loads(line)
                candidate_id = payload["id"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise SystemExit(
                    f"invalid candidate JSONL at {path}:{line_number}"
                ) from exc
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                raise SystemExit(f"invalid candidate id at {path}:{line_number}")
            ids.add(candidate_id.strip())
    return ids


def _refuse_high_risk_overwrite(out_dir: Path) -> None:
    existing = [
        path
        for path in (
            out_dir / "candidates.jsonl",
            out_dir / "annotation.csv",
            out_dir / "manifest.json",
        )
        if path.exists()
    ]
    if existing:
        names = ", ".join(str(path) for path in existing)
        raise SystemExit(f"refusing to overwrite existing high-risk output: {names}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream Civil Comments and create candidates.jsonl plus annotation.csv."
    )
    parser.add_argument("--mode", choices=("standard", "high-risk"), default="standard")
    parser.add_argument("--safe", type=_non_negative_int, default=30)
    parser.add_argument("--gray", type=_non_negative_int, default=70)
    parser.add_argument("--harmful", type=_non_negative_int, default=30)
    parser.add_argument("--threat", type=_non_negative_int, default=12)
    parser.add_argument("--identity-hate", type=_non_negative_int, default=10)
    parser.add_argument("--severe-toxic", type=_non_negative_int, default=8)
    parser.add_argument("--threat-min", type=_unit_interval_float, default=THREAT_MIN)
    parser.add_argument("--identity-min", type=_unit_interval_float, default=IDENTITY_HATE_MIN)
    parser.add_argument("--severe-min", type=_unit_interval_float, default=SEVERE_TOXIC_MIN)
    parser.add_argument(
        "--exclude-candidates",
        default="data/system_eval/candidates.jsonl",
        help="candidate JSONL whose IDs high-risk mode must exclude",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="sampling seed (default: 42 standard, 43 high-risk)",
    )
    parser.add_argument(
        "--revision",
        default="main",
        help="Hugging Face dataset revision; main is resolved to an immutable commit SHA",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="output directory (mode-specific default when omitted)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    high_risk = args.mode == "high-risk"
    if high_risk and args.threat + args.identity_hate + args.severe_toxic == 0:
        raise SystemExit(
            "at least one of --threat/--identity-hate/--severe-toxic must be greater than zero"
        )
    if not high_risk and args.safe + args.gray + args.harmful == 0:
        raise SystemExit("at least one of --safe/--gray/--harmful must be greater than zero")

    seed = args.seed if args.seed is not None else (43 if high_risk else 42)
    out_dir = Path(
        args.out_dir
        or ("data/system_eval/high_risk_addendum" if high_risk else "data/system_eval")
    )
    excluded_ids: set[str] = set()
    if high_risk:
        _refuse_high_risk_overwrite(out_dir)
        excluded_ids = _candidate_ids(Path(args.exclude_candidates))

    try:
        from datasets import load_dataset
        from huggingface_hub import HfApi
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Hugging Face datasets is required for this script; install it with "
            "`python -m pip install -e \".[eval]\"`."
        ) from exc

    resolved_revision = HfApi().dataset_info(DATASET_ID, revision=args.revision).sha
    print(
        f"streaming {DATASET_ID}@{resolved_revision} "
        "(the dataset is not materialized in memory) ..."
    )
    rows = load_dataset(
        DATASET_ID,
        split=DATASET_SPLIT,
        streaming=True,
        revision=resolved_revision,
    )
    if high_risk:
        candidates = sample_high_risk_civil_comments(
            rows,
            threat=args.threat,
            identity_hate=args.identity_hate,
            severe_toxic=args.severe_toxic,
            seed=seed,
            exclude_ids=excluded_ids,
            threat_min=args.threat_min,
            identity_min=args.identity_min,
            severe_min=args.severe_min,
        )
        quotas = {
            "threat": args.threat,
            "identity_hate": args.identity_hate,
            "severe_toxic": args.severe_toxic,
        }
    else:
        candidates = sample_civil_comments(
            rows,
            safe=args.safe,
            gray=args.gray,
            harmful=args.harmful,
            seed=seed,
        )
        quotas = {
            "safe": args.safe,
            "gray": args.gray,
            "harmful": args.harmful,
        }
    jsonl_path, csv_path = write_candidate_files(candidates, out_dir)
    manifest_path = out_dir / "manifest.json"
    manifest: dict[str, object] = {
        "dataset_id": DATASET_ID,
        "dataset_revision": resolved_revision,
        "dataset_split": DATASET_SPLIT,
        "mode": args.mode,
        "seed": seed,
        "quotas": quotas,
        "slice_thresholds": {
            "safe_max": SAFE_MAX,
            "gray_min": GRAY_MIN,
            "gray_max": GRAY_MAX,
            "harmful_min": HARMFUL_MIN,
        },
    }
    if high_risk:
        manifest.update(
            {
                "score_thresholds": {
                    "threat": args.threat_min,
                    "identity_hate": args.identity_min,
                    "severe_toxic": args.severe_min,
                },
                "assignment_priority": ["threat", "identity_hate", "severe_toxic"],
                "exclude_candidates": str(Path(args.exclude_candidates)),
                "excluded_id_count": len(excluded_ids),
            }
        )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(candidates)} candidates -> {jsonl_path}")
    print(f"fill the gold_* columns and rationale -> {csv_path}")
    print(f"dataset provenance -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
