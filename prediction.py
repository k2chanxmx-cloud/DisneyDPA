from datetime import date, datetime, timedelta
from typing import Any
from utils import time_to_minutes, minutes_to_time, weighted_average, weighted_quantile

def normalize_weather(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if "雨" in text:
        return "雨"
    if "雪" in text:
        return "雪"
    if "曇" in text or "くも" in text:
        return "曇"
    if "晴" in text:
        return "晴"

    return text

def crowd_score_from_label(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None

    mappings = [
        ("閑散", 20),
        ("空", 25),
        ("やや空", 35),
        ("普通", 50),
        ("やや混", 65),
        ("混雑", 80),
        ("非常に混", 95),
    ]

    for keyword, score in mappings:
        if keyword in text:
            return score

    try:
        return int(float(text))
    except ValueError:
        return None

def crowd_label_from_score(score: float | None) -> str:
    if score is None:
        return "データ不足"
    if score < 30:
        return "空いている"
    if score < 45:
        return "やや空いている"
    if score < 60:
        return "普通"
    if score < 75:
        return "やや混雑"
    if score < 90:
        return "混雑"
    return "非常に混雑"

def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and str(value).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _date_profile(value: datetime) -> dict[str, Any]:
    """日付だけから安定して判定できる季節・休暇プロフィールを返す。"""
    month = value.month
    day = value.day
    is_weekend = value.weekday() >= 5

    if month in (12, 1, 2):
        season = "winter"
    elif month in (3, 4, 5):
        season = "spring"
    elif month in (6, 7, 8):
        season = "summer"
    else:
        season = "autumn"

    # 全国で完全には一致しないため、学校休暇は「傾向」としてのみ使う。
    school_break = "none"
    if (month == 7 and day >= 20) or month == 8:
        school_break = "summer"
    elif (month == 12 and day >= 24) or (month == 1 and day <= 7):
        school_break = "winter"
    elif (month == 3 and day >= 20) or (month == 4 and day <= 7):
        school_break = "spring"

    event_season = "normal"
    if month == 10:
        event_season = "halloween"
    elif month == 12:
        event_season = "christmas"
    elif month == 1 and day <= 7:
        event_season = "new_year"
    elif (month == 4 and day >= 29) or (month == 5 and day <= 6):
        event_season = "golden_week"

    return {
        "weekday": value.weekday(),
        "is_weekend": is_weekend,
        "season": season,
        "school_break": school_break,
        "event_season": event_season,
    }


FEATURE_WEIGHTS: dict[str, dict[str, float]] = {
    "default_v5": {
        "weekday": 30.0,
        "school_break": 15.0,
        "season_event": 15.0,
        "weather": 10.0,
        "temperature": 10.0,
        "open_time": 8.0,
        "ticket_price": 7.0,
        "recency": 5.0,
    },
    "beauty_v1": {
        "weekday": 27.0,
        "school_break": 18.0,
        "season_event": 20.0,
        "weather": 5.0,
        "temperature": 5.0,
        "open_time": 10.0,
        "ticket_price": 10.0,
        "recency": 5.0,
    },
    "baymax_v1": {
        "weekday": 24.0,
        "school_break": 20.0,
        "season_event": 13.0,
        "weather": 8.0,
        "temperature": 18.0,
        "open_time": 7.0,
        "ticket_price": 5.0,
        "recency": 5.0,
    },
    "splash_v1": {
        "weekday": 15.0,
        "school_break": 12.0,
        "season_event": 18.0,
        "weather": 15.0,
        "temperature": 25.0,
        "open_time": 5.0,
        "ticket_price": 5.0,
        "recency": 5.0,
    },
}

ATTRACTION_SCORING_PROFILES = {
    "beauty": "beauty_v1",
    "baymax": "baymax_v1",
    "splash": "splash_v1",
}

SIMILARITY_THRESHOLDS = (80.0, 75.0, 70.0)
MIN_SELECTED_HISTORY = 50
MAX_SELECTED_HISTORY = 120


def get_scoring_profile(
    attraction_code: str | None = None,
    learned_weights: dict[str, dict[str, float]] | None = None,
) -> tuple[str, dict[str, float]]:
    profile_name = ATTRACTION_SCORING_PROFILES.get(
        str(attraction_code or "").strip(),
        "default_v5",
    )
    code = str(attraction_code or "").strip()
    if learned_weights and code in learned_weights:
        return profile_name + "_adaptive", dict(learned_weights[code])
    return profile_name, dict(FEATURE_WEIGHTS[profile_name])


def similarity_score_details(
    row: dict[str, Any],
    target_dt: datetime,
    day_info: dict[str, Any],
    attraction_code: str | None = None,
    learned_weights: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Ver5.0.2のアトラクション別100点式類似度と内訳を返す。"""
    visit_date = row.get("visit_date")
    profile_name, weights = get_scoring_profile(attraction_code, learned_weights)
    if not visit_date:
        return {"score": 0.0, "components": {}, "visit_date": None, "profile": profile_name}

    try:
        history_dt = datetime.strptime(str(visit_date), "%Y-%m-%d")
    except ValueError:
        return {"score": 0.0, "components": {}, "visit_date": str(visit_date), "profile": profile_name}

    target_profile = _date_profile(target_dt)
    history_profile = _date_profile(history_dt)
    ratios: dict[str, float] = {}

    if history_profile["weekday"] == target_profile["weekday"]:
        ratios["weekday"] = 1.0
    elif history_profile["is_weekend"] == target_profile["is_weekend"]:
        ratios["weekday"] = 0.6
    else:
        ratios["weekday"] = 1.0 / 6.0

    if history_profile["school_break"] == target_profile["school_break"]:
        ratios["school_break"] = 1.0
    elif "none" in (history_profile["school_break"], target_profile["school_break"]):
        ratios["school_break"] = 4.0 / 15.0
    else:
        ratios["school_break"] = 8.0 / 15.0

    event_ratio = 0.0
    if history_profile["event_season"] == target_profile["event_season"]:
        event_ratio += 0.6
    elif "normal" in (history_profile["event_season"], target_profile["event_season"]):
        event_ratio += 2.0 / 15.0
    if history_profile["season"] == target_profile["season"]:
        event_ratio += 0.4
    elif abs(history_dt.month - target_dt.month) in (1, 11):
        event_ratio += 0.2
    ratios["season_event"] = min(1.0, event_ratio)

    target_weather = normalize_weather(day_info.get("weather"))
    history_weather = normalize_weather(row.get("weather"))
    if target_weather and history_weather:
        ratios["weather"] = 1.0 if target_weather == history_weather else 0.2
    else:
        ratios["weather"] = 0.5

    target_high = _safe_float(day_info.get("temperature_high"))
    history_high = _safe_float(row.get("temperature_high"))
    target_low = _safe_float(day_info.get("temperature_low"))
    history_low = _safe_float(row.get("temperature_low"))
    temperature_diffs = []
    if target_high is not None and history_high is not None:
        temperature_diffs.append(abs(target_high - history_high))
    if target_low is not None and history_low is not None:
        temperature_diffs.append(abs(target_low - history_low))
    if temperature_diffs:
        avg_diff = sum(temperature_diffs) / len(temperature_diffs)
        ratios["temperature"] = max(0.0, 1.0 - avg_diff / 8.0)
    else:
        ratios["temperature"] = 0.5

    target_open = time_to_minutes(day_info.get("official_open_time"))
    history_open = time_to_minutes(row.get("official_open_time"))
    if target_open is not None and history_open is not None:
        ratios["open_time"] = max(0.0, 1.0 - abs(target_open - history_open) / 120.0)
    else:
        ratios["open_time"] = 0.5

    target_price = _safe_float(day_info.get("ticket_price"))
    history_price = _safe_float(row.get("ticket_price"))
    if target_price is not None and history_price is not None:
        ratios["ticket_price"] = max(0.0, 1.0 - abs(target_price - history_price) / 3500.0)
    else:
        ratios["ticket_price"] = 0.5

    age_days = abs((target_dt.date() - history_dt.date()).days)
    ratios["recency"] = max(0.1, 1.0 - age_days / 3650.0)

    components = {
        key: weights[key] * max(0.0, min(1.0, ratios.get(key, 0.0)))
        for key in weights
    }
    score = max(0.01, min(100.0, sum(components.values())))
    return {
        "visit_date": history_dt.date().isoformat(),
        "score": round(score, 2),
        "profile": profile_name,
        "components": {key: round(value, 2) for key, value in components.items()},
    }


def select_similar_rows(
    scored_rows: list[tuple[dict[str, Any], dict[str, Any]]],
    minimum_count: int = MIN_SELECTED_HISTORY,
    maximum_count: int = MAX_SELECTED_HISTORY,
) -> tuple[list[tuple[dict[str, Any], float]], float | None, str]:
    """高スコアを優先し、不足時だけ基準を段階的に緩和する。"""
    ordered = sorted(
        scored_rows,
        key=lambda item: float(item[1].get("score") or 0),
        reverse=True,
    )
    for threshold in SIMILARITY_THRESHOLDS:
        candidates = [
            (row, float(details["score"]))
            for row, details in ordered
            if float(details.get("score") or 0) >= threshold
        ]
        if len(candidates) >= minimum_count:
            return candidates[:maximum_count], threshold, "threshold"

    fallback = [
        (row, float(details["score"]))
        for row, details in ordered[:minimum_count]
    ]
    cutoff = fallback[-1][1] if fallback else None
    return fallback, cutoff, "minimum_count_fallback"

def similarity_weight(
    row: dict[str, Any],
    target_dt: datetime,
    day_info: dict[str, Any],
) -> float:
    """既存呼び出しとの互換性を保ちながらVer5スコアを重みに使う。"""
    return float(similarity_score_details(row, target_dt, day_info)["score"])

def build_attraction_prediction(
    history_rows: list[dict[str, Any]],
    weighted_rows: list[tuple[dict[str, Any], float]],
    entry_minutes: int,
    code: str,
    name: str,
    sellout_field: str,
    limit_field: str,
    scoring_profile: str | None = None,
    minimum_similarity_score: float | None = None,
    selection_mode: str | None = None,
    feature_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    availability_values: list[tuple[float, float]] = []
    sellout_values: list[tuple[float, float]] = []
    limit_weight = 0.0
    known_weight = 0.0

    for row, weight in weighted_rows:
        sellout_minutes = time_to_minutes(row.get(sellout_field))
        is_limit = bool(row.get(limit_field))

        if is_limit:
            availability_values.append((1.0, weight))
            limit_weight += weight
            known_weight += weight
            continue

        if sellout_minutes is None:
            # 売り切れ時刻が欠損している行は確率計算から除外する。
            continue

        availability_values.append(
            (1.0 if sellout_minutes >= entry_minutes else 0.0, weight)
        )
        sellout_values.append((float(sellout_minutes), weight))
        known_weight += weight

    probability_average = weighted_average(availability_values)
    probability = (
        int(round(probability_average * 100))
        if probability_average is not None
        else 0
    )

    predicted_minutes = weighted_quantile(sellout_values, 0.50)
    confidence_low = weighted_quantile(sellout_values, 0.20)
    confidence_high = weighted_quantile(sellout_values, 0.80)

    limit_ratio = (
        limit_weight / known_weight
        if known_weight > 0
        else 0.0
    )

    if limit_ratio >= 0.55:
        predicted_sellout_time = "記録上限まで残る予測"
        high_text = "記録上限"
    else:
        predicted_sellout_time = minutes_to_time(predicted_minutes)
        high_text = minutes_to_time(confidence_high)

    return {
        "attraction_code": code,
        "name": name,
        "acquisition_probability": probability,
        "predicted_sellout_time": predicted_sellout_time,
        "confidence_low": minutes_to_time(confidence_low),
        "confidence_high": high_text,
        "sample_count": len(availability_values),
        "selected_history_count": len(weighted_rows),
        "scoring_profile": scoring_profile,
        "minimum_similarity_score": round(minimum_similarity_score, 2) if minimum_similarity_score is not None else None,
        "selection_mode": selection_mode,
        "feature_weights": feature_weights or {},
    }

def calculate_prediction_confidence(
    attractions: list[dict[str, Any]],
    selected_count: int,
    history_count: int,
    used_condition_count: int,
    learning_applied: bool,
) -> dict[str, Any]:
    """予測材料の量と売切れ時刻レンジから、説明用の信頼度を算出する。"""
    sample_scores = []
    range_scores = []

    for item in attractions:
        sample_count = int(item.get("sample_count") or 0)
        sample_scores.append(min(100.0, sample_count / 80.0 * 100.0))

        low = time_to_minutes(item.get("confidence_low"))
        high = time_to_minutes(item.get("confidence_high"))
        if low is not None and high is not None and high >= low:
            width = high - low
            # 60分以内は高評価、6時間以上は低評価。
            range_scores.append(max(0.0, min(100.0, 115.0 - width / 3.0)))

    sample_score = sum(sample_scores) / len(sample_scores) if sample_scores else 0.0
    range_score = sum(range_scores) / len(range_scores) if range_scores else 45.0
    selected_score = min(100.0, selected_count / 100.0 * 100.0)
    history_score = min(100.0, history_count / 300.0 * 100.0)
    condition_score = min(100.0, used_condition_count / 3.0 * 100.0)
    learning_bonus = 5.0 if learning_applied else 0.0

    score = round(
        sample_score * 0.30
        + range_score * 0.25
        + selected_score * 0.20
        + history_score * 0.15
        + condition_score * 0.10
        + learning_bonus
    )
    score = max(1, min(99, score))

    if score >= 85:
        label, stars = "高い", 5
    elif score >= 70:
        label, stars = "やや高い", 4
    elif score >= 55:
        label, stars = "標準", 3
    elif score >= 40:
        label, stars = "やや低い", 2
    else:
        label, stars = "低い", 1

    return {
        "score": score,
        "label": label,
        "stars": stars,
        "stars_text": "★" * stars + "☆" * (5 - stars),
        "components": {
            "sample_score": round(sample_score),
            "sellout_range_score": round(range_score),
            "selected_history_score": round(selected_score),
            "total_history_score": round(history_score),
            "condition_score": round(condition_score),
            "learning_bonus": int(learning_bonus),
        },
    }
