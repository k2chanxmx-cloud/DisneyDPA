from __future__ import annotations

from math import sqrt
from typing import Any
import re

from prediction import FEATURE_WEIGHTS, ATTRACTION_SCORING_PROFILES
from utils import time_to_minutes

FEATURE_KEYS = (
    "weekday",
    "school_break",
    "season_event",
    "weather",
    "temperature",
    "open_time",
    "ticket_price",
    "recency",
)

MIN_EVALUATIONS = 10
FULL_STRENGTH_EVALUATIONS = 100
MAX_RELATIVE_CHANGE = 0.20
MIN_WEIGHT = 3.0
MAX_WEIGHT = 35.0


def _time_minutes(value: Any) -> int | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", text):
        return None
    return time_to_minutes(text)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denominator = sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    if denominator <= 1e-9:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denominator


def _learning_strength(count: int) -> float:
    if count < MIN_EVALUATIONS:
        return 0.0
    return min(1.0, (count - MIN_EVALUATIONS + 1) / (FULL_STRENGTH_EVALUATIONS - MIN_EVALUATIONS + 1))


def _extract_feature_match(payload: dict[str, Any], code: str, feature: str) -> float | None:
    try:
        attraction = payload["similarity_scoring"]["attractions"][code]
        days = attraction.get("similar_days") or []
        weights = attraction.get("feature_weights") or {}
        base_weight = float(weights.get(feature) or 0.0)
        if base_weight <= 0 or not days:
            return None
        ratios = []
        for day in days[:5]:
            component = float((day.get("components") or {}).get(feature) or 0.0)
            ratios.append(max(0.0, min(1.0, component / base_weight)))
        return sum(ratios) / len(ratios) if ratios else None
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def build_adaptive_feature_profiles(evaluated_logs: list[dict[str, Any]]) -> dict[str, Any]:
    """評価済みログから、特徴一致度と予測誤差の関係を使って安全に重みを微調整する。

    一致度が高いほど絶対誤差が小さくなる特徴は増量し、逆の特徴は減量する。
    変更幅は基準値の±20%以内、合計100点に再正規化する。
    """
    result: dict[str, Any] = {
        "engine": "adaptive_feature_learning_v6_1",
        "applied": False,
        "minimum_evaluations": MIN_EVALUATIONS,
        "maximum_relative_change": MAX_RELATIVE_CHANGE,
        "attractions": {},
        "profiles": {},
    }

    for code, profile_name in ATTRACTION_SCORING_PROFILES.items():
        base_weights = dict(FEATURE_WEIGHTS[profile_name])
        samples: dict[str, list[tuple[float, float]]] = {key: [] for key in FEATURE_KEYS}
        evaluated_count = 0

        for log in evaluated_logs:
            predicted = _time_minutes(log.get(f"{code}_predicted_sellout_time"))
            actual = _time_minutes(log.get(f"{code}_actual_sellout_time"))
            payload = log.get("prediction_payload")
            if predicted is None or actual is None or not isinstance(payload, dict):
                continue
            absolute_error = float(abs(actual - predicted))
            evaluated_count += 1
            for feature in FEATURE_KEYS:
                match = _extract_feature_match(payload, code, feature)
                if match is not None:
                    samples[feature].append((match, absolute_error))

        strength = _learning_strength(evaluated_count)
        raw_adjustments: dict[str, float] = {}
        correlations: dict[str, float | None] = {}
        sample_counts: dict[str, int] = {}

        for feature in FEATURE_KEYS:
            pairs = samples[feature]
            sample_counts[feature] = len(pairs)
            corr = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
            correlations[feature] = round(corr, 4) if corr is not None else None
            # 負の相関 = 一致度が高いほど誤差が小さい = 重みを増やす。
            signal = -corr if corr is not None else 0.0
            raw_adjustments[feature] = max(-1.0, min(1.0, signal)) * MAX_RELATIVE_CHANGE * strength

        adjusted = {
            feature: max(
                MIN_WEIGHT,
                min(MAX_WEIGHT, base_weights[feature] * (1.0 + raw_adjustments[feature])),
            )
            for feature in FEATURE_KEYS
        }
        total = sum(adjusted.values()) or 100.0
        normalized = {feature: round(adjusted[feature] * 100.0 / total, 2) for feature in FEATURE_KEYS}
        # 丸め後も合計100に合わせる。
        diff = round(100.0 - sum(normalized.values()), 2)
        normalized[max(normalized, key=normalized.get)] = round(normalized[max(normalized, key=normalized.get)] + diff, 2)

        applied = strength > 0 and any(abs(normalized[k] - base_weights[k]) >= 0.05 for k in FEATURE_KEYS)
        if applied:
            result["applied"] = True

        result["profiles"][code] = normalized
        result["attractions"][code] = {
            "profile": profile_name,
            "evaluated_count": evaluated_count,
            "learning_strength": round(strength, 3),
            "applied": applied,
            "base_weights": base_weights,
            "learned_weights": normalized,
            "weight_changes": {k: round(normalized[k] - base_weights[k], 2) for k in FEATURE_KEYS},
            "feature_error_correlations": correlations,
            "feature_sample_counts": sample_counts,
            "reason": (
                f"評価済み{evaluated_count}件を使い、特徴一致度と絶対誤差の相関から重みを調整しました。"
                if applied else
                f"特徴量学習には最低{MIN_EVALUATIONS}件の評価済み予測が必要です。現在は{evaluated_count}件です。"
            ),
        }

    return result
