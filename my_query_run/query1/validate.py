#!/usr/bin/env python3
"""Validation helper for a single DAB benchmark query."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        return _normalize(parsed)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def _load_ground_truth() -> str:
    ground_truth_path = Path(__file__).with_name("ground_truth.csv")
    if not ground_truth_path.exists():
        return ""
    return ground_truth_path.read_text(encoding="utf-8").strip()


def _coerce_query_df(query_df: Any) -> Any:
    if hasattr(query_df, "to_dict"):
        try:
            return query_df.to_dict(orient="records")
        except TypeError:
            return query_df.to_dict()
    return query_df


def validate(query_df: Any, llm_answer: str, team_name: str = "Team PaLM", team_reason: str = "") -> dict:
    ground_truth_raw = _load_ground_truth()
    normalized_ground_truth = _normalize(ground_truth_raw) if ground_truth_raw else ""
    normalized_answer = _normalize(llm_answer)
    normalized_query_df = _normalize(_coerce_query_df(query_df))

    is_valid = False
    reason = team_reason or "Ground truth missing."

    if ground_truth_raw:
        is_valid = normalized_answer == normalized_ground_truth or normalized_query_df == normalized_ground_truth
        reason = team_reason or ("Answer matches ground truth." if is_valid else "Answer does not match ground truth.")

    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "query_name": Path(__file__).parent.name,
        "is_valid": is_valid,
        "reason": reason,
        "ground_truth": ground_truth_raw,
        "llm_answer": llm_answer,
    }


if __name__ == "__main__":
    raise SystemExit("Import validate() from this module to run benchmark validation.")
