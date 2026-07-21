from __future__ import annotations

from statistics import median
from typing import Any

from utils import minutes_to_time, time_to_minutes

MODEL_LABELS = {
    "season_event": "季節・イベント最適化モデル",
    "adaptive_bias": "誤差補正モデル",
    "recent_trend": "直近傾向モデル",
    "robust_median": "類似日中央値モデル",
}

MIN_MODEL_EVALUATIONS = 10


def _valid_time(value: Any) -> int | None:
    minutes = time_to_minutes(value)
    return minutes if minutes is not None and 0 <= minutes < 24 * 60 else None


def _candidate_from_rows(rows: list[dict[str, Any]], field: str, recent_limit: int | None = None) -> int | None:
    source = rows[:recent_limit] if recent_limit else rows
    values = [_valid_time(row.get(field)) for row in source]
    valid = [value for value in values if value is not None]
    return int(round(median(valid))) if valid else None


def _extract_historical_candidate(log: dict[str, Any], code: str, model_id: str) -> int | None:
    payload = log.get("prediction_payload")
    if not isinstance(payload, dict):
        return None
    hybrid = payload.get("hybrid_ai")
    if not isinstance(hybrid, dict):
        return None
    attraction = (hybrid.get("attractions") or {}).get(code)
    if not isinstance(attraction, dict):
        return None
    candidate = (attraction.get("candidates") or {}).get(model_id)
    if isinstance(candidate, dict):
        return _valid_time(candidate.get("prediction"))
    return _valid_time(candidate)


def _model_accuracy(logs: list[dict[str, Any]], code: str) -> dict[str, dict[str, Any]]:
    actual_field = f"{code}_actual_sellout_time"
    stats: dict[str, dict[str, Any]] = {}
    for model_id in MODEL_LABELS:
        errors: list[int] = []
        for log in logs:
            actual = _valid_time(log.get(actual_field))
            predicted = _extract_historical_candidate(log, code, model_id)
            if actual is not None and predicted is not None:
                errors.append(abs(actual - predicted))
        count = len(errors)
        stats[model_id] = {
            "evaluated_count": count,
            "mean_absolute_error_minutes": round(sum(errors) / count, 1) if count else None,
            "eligible": count >= MIN_MODEL_EVALUATIONS,
        }
    return stats


def _cold_start_weights(candidates: dict[str, int | None]) -> dict[str, float]:
    priors = {
        "season_event": 0.40,
        "adaptive_bias": 0.30,
        "recent_trend": 0.20,
        "robust_median": 0.10,
    }
    available = {key: value for key, value in priors.items() if candidates.get(key) is not None}
    total = sum(available.values()) or 1.0
    return {key: round(value / total, 4) for key, value in available.items()}


def apply_hybrid_ai(
    attractions: list[dict[str, Any]],
    evaluated_logs: list[dict[str, Any]],
    selected_rows_by_code: dict[str, list[dict[str, Any]]],
    attraction_fields: dict[str, str],
) -> dict[str, Any]:
    """複数モデルを比較し、十分な評価実績があれば最良モデル、なければ安全なアンサンブルを採用する。"""
    result: dict[str, Any] = {
        "engine": "hybrid_ai_engine_v7",
        "minimum_model_evaluations": MIN_MODEL_EVALUATIONS,
        "selection_policy": "評価10件以上のモデルはMAE最小を採用。評価不足時は事前重み付きアンサンブル。",
        "applied": False,
        "attractions": {},
    }

    for item in attractions:
        code = str(item.get("attraction_code") or "")
        sellout_field = attraction_fields.get(code, f"{code}_sellout_time")
        selected_rows = selected_rows_by_code.get(code, [])
        raw = _valid_time(item.get("raw_prediction") or item.get("predicted_sellout_time"))
        corrected = _valid_time(item.get("corrected_prediction") or item.get("predicted_sellout_time"))
        recent = _candidate_from_rows(selected_rows, sellout_field, recent_limit=20)
        robust = _candidate_from_rows(selected_rows, sellout_field)

        candidates: dict[str, int | None] = {
            "season_event": raw,
            "adaptive_bias": corrected,
            "recent_trend": recent,
            "robust_median": robust,
        }
        accuracy = _model_accuracy(evaluated_logs, code)
        eligible = [
            model_id for model_id, stat in accuracy.items()
            if stat.get("eligible") and candidates.get(model_id) is not None
        ]

        if eligible:
            selected_model = min(
                eligible,
                key=lambda model_id: float(accuracy[model_id]["mean_absolute_error_minutes"]),
            )
            final_minutes = candidates[selected_model]
            mode = "best_model_selection"
            weights = {selected_model: 1.0}
            selection_reason = (
                f"評価済み{accuracy[selected_model]['evaluated_count']}件のMAEが"
                f"{accuracy[selected_model]['mean_absolute_error_minutes']}分で最小のため採用しました。"
            )
        else:
            weights = _cold_start_weights(candidates)
            weighted_values = [
                (candidates[model_id], weight)
                for model_id, weight in weights.items()
                if candidates.get(model_id) is not None
            ]
            final_minutes = int(round(sum(value * weight for value, weight in weighted_values))) if weighted_values else corrected or raw
            selected_model = "weighted_ensemble"
            mode = "cold_start_ensemble"
            selection_reason = (
                "モデル別評価が10件未満のため、季節・誤差補正・直近傾向・類似日中央値を"
                "安全な事前重みで統合しました。"
            )

        final_prediction = minutes_to_time(final_minutes)
        previous_prediction = item.get("predicted_sellout_time")
        item["hybrid_previous_prediction"] = previous_prediction
        item["hybrid_selected_model"] = selected_model
        item["hybrid_selection_mode"] = mode
        item["hybrid_final_prediction"] = final_prediction
        item["predicted_sellout_time"] = final_prediction
        item["corrected_prediction"] = final_prediction

        candidate_payload = {
            model_id: {
                "label": MODEL_LABELS[model_id],
                "prediction": minutes_to_time(value),
                **accuracy[model_id],
                "ensemble_weight": weights.get(model_id, 0.0),
            }
            for model_id, value in candidates.items()
        }
        result["attractions"][code] = {
            "name": item.get("name"),
            "selection_mode": mode,
            "selected_model": selected_model,
            "selected_model_label": "重み付きアンサンブル" if selected_model == "weighted_ensemble" else MODEL_LABELS[selected_model],
            "final_prediction": final_prediction,
            "previous_prediction": previous_prediction,
            "selection_reason": selection_reason,
            "candidates": candidate_payload,
            "ensemble_weights": weights,
        }
        result["applied"] = True

    return result
