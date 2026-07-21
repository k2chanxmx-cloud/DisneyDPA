from __future__ import annotations

from typing import Any
import re

from utils import minutes_to_time, time_to_minutes

ATTRACTION_NAMES = {
    "beauty": "美女と野獣",
    "baymax": "ベイマックス",
    "splash": "スプラッシュ・マウンテン",
}


def _time_minutes(value: Any) -> int | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", text):
        return None
    return time_to_minutes(text)


def correction_rate(evaluated_count: int) -> float:
    """評価件数が少ないうちは補正を弱くし、100件以上で全量適用する。"""
    if evaluated_count < 10:
        return 0.0
    if evaluated_count < 30:
        return 0.20
    if evaluated_count < 60:
        return 0.50
    if evaluated_count < 100:
        return 0.75
    return 1.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def apply_adaptive_bias_correction(
    attractions: list[dict[str, Any]],
    evaluated_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    """アトラクション別の過去誤差から、時刻・取得確率を段階補正する。"""
    result: dict[str, Any] = {
        "engine": "adaptive_bias_correction_v6",
        "evaluated_count": len(evaluated_logs),
        "applied": False,
        "attractions": {},
        "rate_policy": {
            "0-9": 0.0,
            "10-29": 0.20,
            "30-59": 0.50,
            "60-99": 0.75,
            "100+": 1.0,
        },
    }

    for item in attractions:
        code = str(item.get("attraction_code") or "")
        time_errors: list[int] = []
        probability_errors: list[float] = []

        for log in evaluated_logs:
            predicted = _time_minutes(log.get(f"{code}_predicted_sellout_time"))
            actual = _time_minutes(log.get(f"{code}_actual_sellout_time"))
            if predicted is not None and actual is not None:
                time_errors.append(actual - predicted)

            predicted_probability = log.get(f"{code}_predicted_probability")
            actual_available = log.get(f"{code}_actual_available")
            if predicted_probability is not None and actual_available is not None:
                actual_points = 100.0 if bool(actual_available) else 0.0
                probability_errors.append(actual_points - float(predicted_probability))

        time_count = len(time_errors)
        probability_count = len(probability_errors)
        time_rate = correction_rate(time_count)
        probability_rate = correction_rate(probability_count)
        mean_bias = round(sum(time_errors) / time_count, 1) if time_count else None
        probability_bias = (
            round(sum(probability_errors) / probability_count, 1)
            if probability_count
            else None
        )

        raw_prediction = item.get("predicted_sellout_time")
        applied_minutes = 0
        corrected_prediction = raw_prediction
        if mean_bias is not None and _time_minutes(raw_prediction) is not None:
            # 外れ値による暴走を防ぐため、平均誤差は±90分、実適用は±60分に制限する。
            safe_bias = _clamp(mean_bias, -90.0, 90.0)
            applied_minutes = int(round(_clamp(safe_bias * time_rate, -60.0, 60.0)))
            corrected_prediction = minutes_to_time((_time_minutes(raw_prediction) or 0) + applied_minutes)
            item["raw_prediction"] = raw_prediction
            item["bias_minutes"] = mean_bias
            item["bias_evaluated_count"] = time_count
            item["bias_apply_rate"] = time_rate
            item["bias_applied_minutes"] = applied_minutes
            item["corrected_prediction"] = corrected_prediction
            item["predicted_sellout_time"] = corrected_prediction
            item["bias_reason"] = (
                f"過去{time_count}件の平均誤差は{mean_bias:+.1f}分です。"
                f"評価件数に応じて{int(time_rate * 100)}%を適用し、"
                f"{applied_minutes:+d}分補正しました。"
            )
            if applied_minutes != 0:
                result["applied"] = True
        else:
            item.update({
                "raw_prediction": raw_prediction,
                "bias_minutes": mean_bias,
                "bias_evaluated_count": time_count,
                "bias_apply_rate": time_rate,
                "bias_applied_minutes": 0,
                "corrected_prediction": corrected_prediction,
                "bias_reason": "補正に必要な売切れ時刻の評価データがまだありません。",
            })

        raw_probability = item.get("acquisition_probability")
        probability_applied = 0
        corrected_probability = raw_probability
        if probability_bias is not None and raw_probability is not None:
            safe_probability_bias = _clamp(probability_bias, -15.0, 15.0)
            probability_applied = int(round(safe_probability_bias * probability_rate))
            corrected_probability = int(_clamp(float(raw_probability) + probability_applied, 1.0, 99.0))
            item["raw_acquisition_probability"] = raw_probability
            item["probability_bias_points"] = probability_bias
            item["probability_bias_evaluated_count"] = probability_count
            item["probability_bias_apply_rate"] = probability_rate
            item["probability_bias_applied_points"] = probability_applied
            item["acquisition_probability"] = corrected_probability
            if probability_applied != 0:
                result["applied"] = True

        result["attractions"][code] = {
            "name": ATTRACTION_NAMES.get(code, item.get("name")),
            "time_evaluated_count": time_count,
            "bias_minutes": mean_bias,
            "apply_rate": time_rate,
            "applied_minutes": applied_minutes,
            "raw_prediction": raw_prediction,
            "corrected_prediction": corrected_prediction,
            "probability_evaluated_count": probability_count,
            "probability_bias_points": probability_bias,
            "probability_applied_points": probability_applied,
            "raw_probability": raw_probability,
            "corrected_probability": corrected_probability,
        }

    return result
