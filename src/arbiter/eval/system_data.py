"""Data preparation and annotation contracts for the system-level evaluation.

The sampler consumes an iterable, so it works with both ordinary Python rows and
Hugging Face streaming datasets.  No Hugging Face dependency is imported here.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from arbiter.moderation_policy import ACTION_SEVERITIES


DATASET_ID = "google/civil_comments"
DATASET_SPLIT = "train"

CATEGORIES = (
    "toxic",
    "severe_toxic",
    "obscene",
    "threat",
    "insult",
    "identity_hate",
)
ACTIONS = ("allow", "human-review", "remove")
SLICES = ("safe", "gray", "harmful")

SAFE_MAX = 0.10
GRAY_MIN = 0.30
GRAY_MAX = 0.70
HARMFUL_MIN = 0.90

HIGH_RISK_PRIORITY = ("threat", "identity_hate", "severe_toxic")
THREAT_MIN = 0.50
IDENTITY_HATE_MIN = 0.50
SEVERE_TOXIC_MIN = 0.20

CANDIDATE_FIELDS = (
    "id",
    "text",
    "source",
    "source_score",
    "source_scores",
    "slice",
)
ANNOTATION_FIELDS = (
    "id",
    "text",
    "source",
    "source_score",
    "gold_action",
    "gold_categories",
    "gold_severity",
    "slice",
    "rationale",
)

_SOURCE_SCORE_FIELDS = {
    "toxic": "toxicity",
    "severe_toxic": "severe_toxicity",
    "obscene": "obscene",
    "threat": "threat",
    "insult": "insult",
    "identity_hate": "identity_attack",
}
_CATEGORY_SEPARATOR = ";"


class SystemEvalDataError(ValueError):
    """Raised when sampling or annotation data violates the data contract."""


class InsufficientSamplesError(SystemEvalDataError):
    """Raised when the input stream cannot satisfy all requested slice quotas."""


@dataclass(frozen=True)
class SamplingQuotas:
    safe: int = 30
    gray: int = 70
    harmful: int = 30

    def __post_init__(self) -> None:
        for name in SLICES:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SystemEvalDataError(f"{name} quota must be a non-negative integer")
        if self.total == 0:
            raise SystemEvalDataError("at least one sampling quota must be greater than zero")

    @property
    def total(self) -> int:
        return self.safe + self.gray + self.harmful

    def as_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in SLICES}


def toxicity_slice(score: float) -> str | None:
    """Map a Civil Comments toxicity score to an evaluation slice.

    Scores in the deliberate gaps (0.10, 0.30) and (0.70, 0.90) are excluded.
    """

    if score <= SAFE_MAX:
        return "safe"
    if GRAY_MIN <= score <= GRAY_MAX:
        return "gray"
    if score >= HARMFUL_MIN:
        return "harmful"
    return None


def _score(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise SystemEvalDataError(f"{field} must be a number between 0 and 1")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise SystemEvalDataError(f"{field} must be a number between 0 and 1") from exc
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise SystemEvalDataError(f"{field} must be a number between 0 and 1")
    return result


def _candidate_id(row: Mapping[str, object], text: str) -> str:
    source_id = row.get("id")
    if source_id is not None and str(source_id).strip():
        return f"civil-comments-{str(source_id).strip()}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]
    return f"civil-comments-{digest}"


def _candidate_from_row(
    row: Mapping[str, object], *, min_text_chars: int, max_text_chars: int
) -> dict[str, object] | None:
    text_value = row.get("text")
    if not isinstance(text_value, str):
        return None
    text = text_value.strip()
    if not min_text_chars <= len(text) <= max_text_chars:
        return None

    try:
        source_score = _score(row.get("toxicity"), field="toxicity")
    except SystemEvalDataError:
        return None
    slice_name = toxicity_slice(source_score)
    if slice_name is None:
        return None

    source_scores: dict[str, float] = {}
    for category, source_field in _SOURCE_SCORE_FIELDS.items():
        # The public dataset has all six fields.  Treat a malformed/missing
        # auxiliary score as unknown (0.0) rather than discarding valid text.
        try:
            source_scores[category] = _score(row.get(source_field, 0.0), field=source_field)
        except SystemEvalDataError:
            source_scores[category] = 0.0

    return {
        "id": _candidate_id(row, text),
        "text": text,
        "source": DATASET_ID,
        "source_score": source_score,
        "source_scores": source_scores,
        "slice": slice_name,
    }


def sample_civil_comments(
    rows: Iterable[Mapping[str, object]],
    *,
    safe: int = 30,
    gray: int = 70,
    harmful: int = 30,
    seed: int = 42,
    min_text_chars: int = 20,
    max_text_chars: int = 500,
) -> list[dict[str, object]]:
    """Select a reproducible stratified sample from Civil Comments rows.

    A separate seeded reservoir is maintained for each slice.  Consequently the
    result is bounded in memory, seed-dependent, and reproducible for the same
    input stream without first materialising the dataset.
    """

    quotas = SamplingQuotas(safe=safe, gray=gray, harmful=harmful)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SystemEvalDataError("seed must be an integer")
    if min_text_chars < 1 or max_text_chars < min_text_chars:
        raise SystemEvalDataError("text length bounds are invalid")

    quota_by_slice = quotas.as_dict()
    reservoirs: dict[str, list[dict[str, object]]] = {name: [] for name in SLICES}
    seen_by_slice = {name: 0 for name in SLICES}
    rng_by_slice = {
        name: random.Random(f"arbiter-system-eval:{seed}:{name}") for name in SLICES
    }
    seen_ids: set[str] = set()

    for row in rows:
        candidate = _candidate_from_row(
            row, min_text_chars=min_text_chars, max_text_chars=max_text_chars
        )
        if candidate is None:
            continue
        candidate_id = str(candidate["id"])
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)

        slice_name = str(candidate["slice"])
        quota = quota_by_slice[slice_name]
        if quota == 0:
            continue
        seen_by_slice[slice_name] += 1
        reservoir = reservoirs[slice_name]
        if len(reservoir) < quota:
            reservoir.append(candidate)
            continue
        replacement = rng_by_slice[slice_name].randrange(seen_by_slice[slice_name])
        if replacement < quota:
            reservoir[replacement] = candidate

    missing = {
        name: quota_by_slice[name] - len(reservoirs[name])
        for name in SLICES
        if len(reservoirs[name]) < quota_by_slice[name]
    }
    if missing:
        details = ", ".join(f"{name}={count}" for name, count in missing.items())
        raise InsufficientSamplesError(f"input stream is short of requested samples: {details}")

    # Canonical ordering makes output byte-for-byte stable for a fixed input/seed.
    selected: list[dict[str, object]] = []
    for slice_name in SLICES:
        selected.extend(sorted(reservoirs[slice_name], key=lambda item: str(item["id"])))
    return selected


def sample_high_risk_civil_comments(
    rows: Iterable[Mapping[str, object]],
    *,
    threat: int = 12,
    identity_hate: int = 10,
    severe_toxic: int = 8,
    seed: int = 43,
    exclude_ids: Iterable[str] | None = None,
    threat_min: float = THREAT_MIN,
    identity_min: float = IDENTITY_HATE_MIN,
    severe_min: float = SEVERE_TOXIC_MIN,
    min_text_chars: int = 20,
    max_text_chars: int = 500,
) -> list[dict[str, object]]:
    """Select a reproducible, non-overlapping high-risk addendum sample.

    Each qualifying row is assigned to the first matching stratum in
    ``threat -> identity_hate -> severe_toxic`` order, then considered by that
    stratum's seeded reservoir.  This stable priority prevents one candidate
    from satisfying multiple quotas.  ``exclude_ids`` is intended for IDs from
    an existing system-evaluation sample so the addendum does not leak cases
    already annotated there.
    """

    quota_by_stratum = {
        "threat": threat,
        "identity_hate": identity_hate,
        "severe_toxic": severe_toxic,
    }
    for name, value in quota_by_stratum.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SystemEvalDataError(f"{name} quota must be a non-negative integer")
    if sum(quota_by_stratum.values()) == 0:
        raise SystemEvalDataError("at least one high-risk quota must be greater than zero")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SystemEvalDataError("seed must be an integer")
    if min_text_chars < 1 or max_text_chars < min_text_chars:
        raise SystemEvalDataError("text length bounds are invalid")

    threshold_by_stratum = {
        "threat": _score(threat_min, field="threat_min"),
        "identity_hate": _score(identity_min, field="identity_min"),
        "severe_toxic": _score(severe_min, field="severe_min"),
    }
    excluded: set[str] = set()
    if exclude_ids is not None:
        if isinstance(exclude_ids, (str, bytes)):
            raise SystemEvalDataError("exclude_ids must be an iterable of candidate IDs")
        for candidate_id in exclude_ids:
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                raise SystemEvalDataError("exclude_ids must contain non-empty strings")
            excluded.add(candidate_id.strip())

    reservoirs: dict[str, list[dict[str, object]]] = {
        name: [] for name in HIGH_RISK_PRIORITY
    }
    seen_by_stratum = {name: 0 for name in HIGH_RISK_PRIORITY}
    rng_by_stratum = {
        name: random.Random(f"arbiter-system-eval-high-risk:{seed}:{name}")
        for name in HIGH_RISK_PRIORITY
    }
    seen_ids: set[str] = set()

    for row in rows:
        candidate = _candidate_from_row(
            row, min_text_chars=min_text_chars, max_text_chars=max_text_chars
        )
        if candidate is None:
            continue
        candidate_id = str(candidate["id"])
        if candidate_id in excluded or candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)

        scores = candidate["source_scores"]
        assert isinstance(scores, Mapping)  # guaranteed by _candidate_from_row
        stratum = next(
            (
                name
                for name in HIGH_RISK_PRIORITY
                if quota_by_stratum[name] > 0
                and float(scores[name]) >= threshold_by_stratum[name]
            ),
            None,
        )
        if stratum is None:
            continue

        quota = quota_by_stratum[stratum]
        seen_by_stratum[stratum] += 1
        reservoir = reservoirs[stratum]
        if len(reservoir) < quota:
            reservoir.append(candidate)
            continue
        replacement = rng_by_stratum[stratum].randrange(seen_by_stratum[stratum])
        if replacement < quota:
            reservoir[replacement] = candidate

    missing = {
        name: quota_by_stratum[name] - len(reservoirs[name])
        for name in HIGH_RISK_PRIORITY
        if len(reservoirs[name]) < quota_by_stratum[name]
    }
    if missing:
        details = ", ".join(f"{name}={count}" for name, count in missing.items())
        raise InsufficientSamplesError(
            f"input stream is short of requested high-risk samples: {details}"
        )

    selected: list[dict[str, object]] = []
    for stratum in HIGH_RISK_PRIORITY:
        selected.extend(sorted(reservoirs[stratum], key=lambda item: str(item["id"])))
    return selected


def _validate_candidate(candidate: Mapping[str, object]) -> None:
    if set(candidate) != set(CANDIDATE_FIELDS):
        raise SystemEvalDataError(
            f"candidate fields must be exactly: {', '.join(CANDIDATE_FIELDS)}"
        )
    if not isinstance(candidate["id"], str) or not candidate["id"]:
        raise SystemEvalDataError("candidate id must be a non-empty string")
    if not isinstance(candidate["text"], str) or not candidate["text"].strip():
        raise SystemEvalDataError("candidate text must be a non-empty string")
    if candidate["source"] != DATASET_ID:
        raise SystemEvalDataError(f"candidate source must be {DATASET_ID!r}")
    source_score = _score(candidate["source_score"], field="source_score")
    if candidate["slice"] not in SLICES or toxicity_slice(source_score) != candidate["slice"]:
        raise SystemEvalDataError("candidate slice does not match source_score")
    scores = candidate["source_scores"]
    if not isinstance(scores, Mapping) or set(scores) != set(CATEGORIES):
        raise SystemEvalDataError("candidate source_scores must contain exactly six categories")
    for category in CATEGORIES:
        _score(scores[category], field=f"source_scores.{category}")


def write_candidate_files(
    candidates: Iterable[Mapping[str, object]], out_dir: str | Path
) -> tuple[Path, Path]:
    """Write ``candidates.jsonl`` and a blank ``annotation.csv`` template."""

    materialized = [dict(candidate) for candidate in candidates]
    if not materialized:
        raise SystemEvalDataError("cannot write an empty candidate sample")
    ids: set[str] = set()
    for candidate in materialized:
        _validate_candidate(candidate)
        candidate_id = str(candidate["id"])
        if candidate_id in ids:
            raise SystemEvalDataError(f"duplicate candidate id: {candidate_id}")
        ids.add(candidate_id)

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    jsonl_path = directory / "candidates.jsonl"
    annotation_path = directory / "annotation.csv"

    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for candidate in materialized:
            payload = {field: candidate[field] for field in CANDIDATE_FIELDS}
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    with annotation_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_FIELDS, lineterminator="\n")
        writer.writeheader()
        for candidate in materialized:
            writer.writerow(
                {
                    "id": candidate["id"],
                    "text": candidate["text"],
                    "source": candidate["source"],
                    "source_score": format(float(candidate["source_score"]), ".17g"),
                    "gold_action": "",
                    "gold_categories": "",
                    "gold_severity": "",
                    "slice": candidate["slice"],
                    "rationale": "",
                }
            )
    return jsonl_path, annotation_path


# Short, discoverable alias for callers that do not need to know both filenames.
write_candidates = write_candidate_files


def _annotation_error(row_number: int | None, message: str) -> SystemEvalDataError:
    prefix = f"annotation row {row_number}: " if row_number is not None else "annotation: "
    return SystemEvalDataError(prefix + message)


def _parse_categories(value: str, *, row_number: int | None) -> list[str]:
    if not value.strip():
        return []
    categories = [part.strip() for part in value.split(_CATEGORY_SEPARATOR)]
    if any(not category for category in categories):
        raise _annotation_error(row_number, "gold_categories contains an empty category")
    invalid = [category for category in categories if category not in CATEGORIES]
    if invalid:
        raise _annotation_error(
            row_number,
            f"unknown gold_categories: {', '.join(invalid)}; use ';' as the separator",
        )
    if len(categories) != len(set(categories)):
        raise _annotation_error(row_number, "gold_categories contains duplicates")
    return [category for category in CATEGORIES if category in categories]


def validate_annotation(
    row: Mapping[str, object], *, row_number: int | None = None
) -> dict[str, object]:
    """Validate and normalize one completed human annotation row."""

    if set(row) != set(ANNOTATION_FIELDS):
        raise _annotation_error(
            row_number, f"fields must be exactly: {', '.join(ANNOTATION_FIELDS)}"
        )
    values = {field: "" if row[field] is None else str(row[field]).strip() for field in ANNOTATION_FIELDS}
    for field in ("id", "text", "source", "source_score", "slice"):
        if not values[field]:
            raise _annotation_error(row_number, f"{field} is required")
    for field in ("gold_action", "gold_severity", "rationale"):
        if not values[field]:
            raise _annotation_error(row_number, f"{field} is incomplete")

    if values["source"] != DATASET_ID:
        raise _annotation_error(row_number, f"source must be {DATASET_ID!r}")
    try:
        source_score = _score(values["source_score"], field="source_score")
    except SystemEvalDataError as exc:
        raise _annotation_error(row_number, str(exc)) from exc
    slice_name = values["slice"]
    if slice_name not in SLICES:
        raise _annotation_error(row_number, f"slice must be one of: {', '.join(SLICES)}")
    if toxicity_slice(source_score) != slice_name:
        raise _annotation_error(row_number, "slice does not match source_score")

    action = values["gold_action"]
    if action not in ACTIONS:
        raise _annotation_error(row_number, f"gold_action must be one of: {', '.join(ACTIONS)}")
    severity_text = values["gold_severity"]
    if severity_text not in {"0", "1", "2", "3"}:
        raise _annotation_error(row_number, "gold_severity must be an integer from 0 to 3")
    severity = int(severity_text)
    categories = _parse_categories(values["gold_categories"], row_number=row_number)

    if severity == 0 and categories:
        raise _annotation_error(row_number, "severity 0 must not have gold_categories")
    if severity > 0 and not categories:
        raise _annotation_error(row_number, "severity above 0 requires gold_categories")
    valid_severity_by_action = ACTION_SEVERITIES
    if severity not in valid_severity_by_action[action]:
        expected = "/".join(str(value) for value in sorted(valid_severity_by_action[action]))
        raise _annotation_error(
            row_number, f"gold_action {action!r} requires gold_severity {expected}"
        )

    return {
        "id": values["id"],
        "text": values["text"],
        "source": values["source"],
        "source_score": source_score,
        "gold_action": action,
        "gold_categories": categories,
        "gold_severity": severity,
        "slice": slice_name,
        "rationale": values["rationale"],
    }


def load_annotations(path: str | Path) -> list[dict[str, object]]:
    """Load a completed annotation CSV, rejecting blanks, drift, and duplicates."""

    annotations: list[dict[str, object]] = []
    ids: set[str] = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SystemEvalDataError("annotation CSV has no header")
        if tuple(reader.fieldnames) != ANNOTATION_FIELDS:
            raise SystemEvalDataError(
                f"annotation CSV header must be exactly: {', '.join(ANNOTATION_FIELDS)}"
            )
        for row_number, row in enumerate(reader, start=2):
            annotation = validate_annotation(row, row_number=row_number)
            annotation_id = str(annotation["id"])
            if annotation_id in ids:
                raise _annotation_error(row_number, f"duplicate id: {annotation_id}")
            ids.add(annotation_id)
            annotations.append(annotation)
    if not annotations:
        raise SystemEvalDataError("annotation CSV contains no rows")
    return annotations
