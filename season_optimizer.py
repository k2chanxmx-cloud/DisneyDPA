from __future__ import annotations

from datetime import datetime
from typing import Any

from feature_learning import build_adaptive_feature_profiles
from prediction import ATTRACTION_SCORING_PROFILES, FEATURE_WEIGHTS

MIN_SEGMENT_EVALUATIONS = 10
FULL_SEGMENT_EVALUATIONS = 60
MAX_SEASONAL_INFLUENCE = 0.45


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def classify_season_context(target_date: Any, factors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """対象日を、通常季節または主要イベント・休暇セグメントへ分類する。"""
    dt = _parse_date(target_date)
    if dt is None:
        return {"segment": "unknown", "label": "判定不能", "source": "none"}

    texts = []
    for factor in factors or []:
        texts.append(str(factor.get("name") or ""))
        texts.append(str(factor.get("category") or ""))
        texts.append(str(factor.get("type_label") or ""))
    joined = " ".join(texts).lower()

    event_rules = (
        ("new_year", "年末年始", ("new year", "ニューイヤー", "正月", "年末年始")),
        ("golden_week", "ゴールデンウィーク", ("golden week", "ゴールデンウィーク", "大型連休")),
        ("halloween", "ハロウィーン", ("halloween", "ハロウィーン", "ハロウィン")),
        ("christmas", "クリスマス", ("christmas", "クリスマス")),
        ("anniversary", "周年イベント", ("周年", "anniversary", "ジュビリー")),
        ("summer_event", "夏イベント", ("サマー", "summer", "クールオフ")),
        ("summer_break", "夏休み", ("夏休み", "summer break")),
        ("spring_break", "春休み", ("春休み", "spring break")),
        ("winter_break", "冬休み", ("冬休み", "winter break")),
    )
    for segment, label, keywords in event_rules:
        if any(keyword.lower() in joined for keyword in keywords):
            return {"segment": segment, "label": label, "source": "yosocal_factors"}

    month, day = dt.month, dt.day
    if month == 10:
        return {"segment": "halloween", "label": "ハロウィーン", "source": "calendar"}
    if month == 12:
        return {"segment": "christmas", "label": "クリスマス", "source": "calendar"}
    if month == 1 and day <= 7:
        return {"segment": "new_year", "label": "年末年始", "source": "calendar"}
    if (month == 4 and day >= 29) or (month == 5 and day <= 6):
        return {"segment": "golden_week", "label": "ゴールデンウィーク", "source": "calendar"}
    if (month == 7 and day >= 20) or month == 8:
        return {"segment": "summer_break", "label": "夏休み", "source": "calendar"}
    if (month == 3 and day >= 20) or (month == 4 and day <= 7):
        return {"segment": "spring_break", "label": "春休み", "source": "calendar"}
    if (month == 12 and day >= 24) or (month == 1 and day <= 7):
        return {"segment": "winter_break", "label": "冬休み", "source": "calendar"}

    season = "winter" if month in (12, 1, 2) else "spring" if month in (3, 4, 5) else "summer" if month in (6, 7, 8) else "autumn"
    labels = {"winter": "通常・冬", "spring": "通常・春", "summer": "通常・夏", "autumn": "通常・秋"}
    return {"segment": f"normal_{season}", "label": labels[season], "source": "calendar"}


def _log_context(log: dict[str, Any]) -> dict[str, Any]:
    payload = log.get("prediction_payload")
    factors = payload.get("yosocal_factors", []) if isinstance(payload, dict) else []
    return classify_season_context(log.get("target_date"), factors)


def _segment_strength(count: int) -> float:
    if count < MIN_SEGMENT_EVALUATIONS:
        return 0.0
    progress = (count - MIN_SEGMENT_EVALUATIONS + 1) / (FULL_SEGMENT_EVALUATIONS - MIN_SEGMENT_EVALUATIONS + 1)
    return max(0.0, min(1.0, progress))


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values()) or 100.0
    result = {key: round(value * 100.0 / total, 2) for key, value in weights.items()}
    diff = round(100.0 - sum(result.values()), 2)
    if result:
        largest = max(result, key=result.get)
        result[largest] = round(result[largest] + diff, 2)
    return result


def build_seasonal_profiles(
    evaluated_logs: list[dict[str, Any]],
    target_date: Any,
    target_factors: list[dict[str, Any]] | None,
    global_profiles: dict[str, dict[str, float]] | None,
) -> dict[str, Any]:
    """同じ季節・イベント区分の評価ログだけで専用重みを学習し、全体学習と安全に融合する。"""
    context = classify_season_context(target_date, target_factors)
    segment_logs = [log for log in evaluated_logs if _log_context(log).get("segment") == context["segment"]]
    seasonal_learning = build_adaptive_feature_profiles(segment_logs)
    segment_count = len(segment_logs)
    strength = _segment_strength(segment_count)
    influence = round(MAX_SEASONAL_INFLUENCE * strength, 3)

    output: dict[str, Any] = {
        "engine": "season_event_optimizer_v6_2",
        "applied": False,
        "target_segment": context["segment"],
        "target_segment_label": context["label"],
        "segment_source": context["source"],
        "segment_evaluated_count": segment_count,
        "minimum_segment_evaluations": MIN_SEGMENT_EVALUATIONS,
        "maximum_seasonal_influence": MAX_SEASONAL_INFLUENCE,
        "seasonal_influence": influence,
        "profiles": {},
        "attractions": {},
    }

    global_profiles = global_profiles or {}
    seasonal_profiles = seasonal_learning.get("profiles", {})
    for code, profile_name in ATTRACTION_SCORING_PROFILES.items():
        base = dict(global_profiles.get(code) or FEATURE_WEIGHTS[profile_name])
        seasonal = dict(seasonal_profiles.get(code) or base)
        seasonal_detail = (seasonal_learning.get("attractions") or {}).get(code, {})
        can_apply = bool(strength > 0 and seasonal_detail.get("applied"))
        blend = influence if can_apply else 0.0
        merged = _normalize({key: base[key] * (1.0 - blend) + seasonal[key] * blend for key in base})
        changed = any(abs(merged[k] - base[k]) >= 0.05 for k in base)
        applied = can_apply and changed
        output["profiles"][code] = merged
        output["attractions"][code] = {
            "profile": profile_name,
            "applied": applied,
            "global_weights": base,
            "seasonal_weights": seasonal,
            "optimized_weights": merged,
            "weight_changes": {key: round(merged[key] - base[key], 2) for key in base},
            "segment_evaluated_count": segment_count,
            "seasonal_influence": blend,
            "reason": (
                f"{context['label']}の評価済み{segment_count}件を使い、全体学習重みへ{round(blend * 100)}%融合しました。"
                if applied else
                f"{context['label']}専用最適化には最低{MIN_SEGMENT_EVALUATIONS}件の評価済み予測が必要です。現在は{segment_count}件です。"
            ),
        }
        output["applied"] = output["applied"] or applied

    return output
