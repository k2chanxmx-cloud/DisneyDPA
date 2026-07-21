from datetime import date, datetime
import re
from typing import Any
from db import supabase_get, supabase_patch, supabase_upsert, supabase_write_enabled
from utils import time_to_minutes, minutes_to_time

def _time_text_to_minutes(value: Any) -> int | None:
    return time_to_minutes(value) if value and re.fullmatch(r"\d{1,2}:\d{2}", str(value)) else None

def apply_learning_calibration(attractions: list[dict[str, Any]], logs: list[dict[str, Any]]) -> dict[str, Any]:
    """Ver6互換ラッパー。段階式の誤差補正エンジンを適用する。"""
    from bias_correction import apply_adaptive_bias_correction
    return apply_adaptive_bias_correction(attractions, logs)

def sync_prediction_results(history_rows: list[dict[str, Any]]) -> int:
    """過去予測に実績を紐付け、次回以降の補正データにする。"""
    if not supabase_write_enabled():
        return 0
    logs = supabase_get("prediction_logs", {
        "select": "*", "target_date": f"lt.{date.today().isoformat()}",
        "evaluated_at": "is.null", "limit": "200"
    })
    history = {str(row.get("visit_date")): row for row in history_rows if row.get("visit_date")}
    count = 0
    for log in logs:
        row = history.get(str(log.get("target_date")))
        if not row:
            continue
        entry = time_to_minutes(log.get("entry_time")) or 600
        values: dict[str, Any] = {"evaluated_at": datetime.utcnow().isoformat() + "Z"}
        for code in ("beauty", "baymax", "splash"):
            actual_text = row.get(f"{code}_sellout_time")
            actual_minutes = time_to_minutes(actual_text)
            is_limit = bool(row.get(f"{code}_is_limit"))
            values[f"{code}_actual_sellout_time"] = actual_text
            values[f"{code}_actual_available"] = is_limit or (actual_minutes is not None and actual_minutes >= entry)
        supabase_patch("prediction_logs", {"id": f"eq.{log['id']}"}, values)
        count += 1
    return count

def save_prediction_log(payload: dict[str, Any]) -> None:
    if not supabase_write_enabled():
        return
    attractions = {item["attraction_code"]: item for item in payload.get("attractions", [])}
    row: dict[str, Any] = {
        "target_date": payload["date"], "entry_time": payload["entry_time"],
        "crowd_score": payload.get("crowd_score"), "ticket_price": payload.get("ticket_price"),
        "official_open_time": payload.get("official_open_time"), "weather": payload.get("weather"),
        "model_version": "adaptive-bias-correction-v6",
        "prediction_payload": payload,
        "predicted_at": datetime.utcnow().isoformat() + "Z",
    }
    for code in ("beauty", "baymax", "splash"):
        item = attractions.get(code, {})
        row[f"{code}_predicted_probability"] = item.get("acquisition_probability")
        value = item.get("predicted_sellout_time")
        row[f"{code}_predicted_sellout_time"] = value if isinstance(value, str) and re.fullmatch(r"\d{2}:\d{2}", value) else None
    supabase_upsert("prediction_logs", [row], "target_date,entry_time,model_version")

def build_accuracy_dashboard(logs: list[dict[str, Any]]) -> dict[str, Any]:
    """評価済み予測ログから、アトラクション別・全体の精度指標を作る。"""
    attraction_names = {
        "beauty": "美女と野獣",
        "baymax": "ベイマックス",
        "splash": "スプラッシュ・マウンテン",
    }
    per_attraction: list[dict[str, Any]] = []
    all_time_errors: list[int] = []
    all_probability_errors: list[float] = []
    all_brier_scores: list[float] = []
    recent_rows: list[dict[str, Any]] = []

    for code, name in attraction_names.items():
        time_errors: list[int] = []
        probability_errors: list[float] = []
        brier_scores: list[float] = []
        probability_correct = 0
        probability_count = 0

        for log in logs:
            predicted = _time_text_to_minutes(log.get(f"{code}_predicted_sellout_time"))
            actual = _time_text_to_minutes(log.get(f"{code}_actual_sellout_time"))
            if predicted is not None and actual is not None:
                error = actual - predicted
                time_errors.append(error)
                all_time_errors.append(error)

            pred_prob = log.get(f"{code}_predicted_probability")
            actual_available = log.get(f"{code}_actual_available")
            if pred_prob is not None and actual_available is not None:
                probability = max(0.0, min(100.0, float(pred_prob)))
                actual_percent = 100.0 if bool(actual_available) else 0.0
                probability_errors.append(actual_percent - probability)
                all_probability_errors.append(actual_percent - probability)
                brier = ((probability / 100.0) - (1.0 if bool(actual_available) else 0.0)) ** 2
                brier_scores.append(brier)
                all_brier_scores.append(brier)
                predicted_available = probability >= 50.0
                probability_correct += int(predicted_available == bool(actual_available))
                probability_count += 1

        count = len(time_errors)
        abs_errors = [abs(value) for value in time_errors]
        per_attraction.append({
            "attraction_code": code,
            "name": name,
            "evaluated_count": count,
            "mean_absolute_error_minutes": round(sum(abs_errors) / count, 1) if count else None,
            "bias_minutes": round(sum(time_errors) / count, 1) if count else None,
            "within_15_minutes_rate": round(sum(1 for value in abs_errors if value <= 15) / count * 100, 1) if count else None,
            "within_30_minutes_rate": round(sum(1 for value in abs_errors if value <= 30) / count * 100, 1) if count else None,
            "within_60_minutes_rate": round(sum(1 for value in abs_errors if value <= 60) / count * 100, 1) if count else None,
            "probability_evaluated_count": probability_count,
            "availability_accuracy_rate": round(probability_correct / probability_count * 100, 1) if probability_count else None,
            "probability_bias_points": round(sum(probability_errors) / len(probability_errors), 1) if probability_errors else None,
            "brier_score": round(sum(brier_scores) / len(brier_scores), 4) if brier_scores else None,
        })

    for log in logs[:30]:
        for code, name in attraction_names.items():
            predicted = _time_text_to_minutes(log.get(f"{code}_predicted_sellout_time"))
            actual = _time_text_to_minutes(log.get(f"{code}_actual_sellout_time"))
            if predicted is None and actual is None:
                continue
            recent_rows.append({
                "target_date": log.get("target_date"),
                "entry_time": log.get("entry_time"),
                "attraction_code": code,
                "name": name,
                "predicted_sellout_time": log.get(f"{code}_predicted_sellout_time"),
                "actual_sellout_time": log.get(f"{code}_actual_sellout_time"),
                "error_minutes": (actual - predicted) if predicted is not None and actual is not None else None,
                "predicted_probability": log.get(f"{code}_predicted_probability"),
                "actual_available": log.get(f"{code}_actual_available"),
                "model_version": log.get("model_version"),
                "evaluated_at": log.get("evaluated_at"),
            })

    total_count = len(all_time_errors)
    total_abs_errors = [abs(value) for value in all_time_errors]
    return {
        "summary": {
            "evaluated_prediction_count": len(logs),
            "evaluated_attraction_count": total_count,
            "mean_absolute_error_minutes": round(sum(total_abs_errors) / total_count, 1) if total_count else None,
            "bias_minutes": round(sum(all_time_errors) / total_count, 1) if total_count else None,
            "within_30_minutes_rate": round(sum(1 for value in total_abs_errors if value <= 30) / total_count * 100, 1) if total_count else None,
            "availability_brier_score": round(sum(all_brier_scores) / len(all_brier_scores), 4) if all_brier_scores else None,
        },
        "attractions": per_attraction,
        "recent_evaluations": recent_rows[:50],
    }
