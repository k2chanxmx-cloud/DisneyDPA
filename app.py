import os
from datetime import date, datetime
from typing import Any

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
REQUEST_TIMEOUT = 15


def supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def supabase_get(
    table: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not supabase_enabled():
        return []

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }

    url = f"{SUPABASE_URL}/rest/v1/{table}"

    response = requests.get(
        url,
        headers=headers,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()
    return response.json()


def time_to_minutes(value: Any) -> int | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    # Supabaseのtime型が HH:MM:SS で返ってきても扱えるようにする。
    text = text[:5]

    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError:
        return None

    return parsed.hour * 60 + parsed.minute


def minutes_to_time(value: float | int | None) -> str | None:
    if value is None:
        return None

    minutes = int(round(float(value)))
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def weighted_average(values: list[tuple[float, float]]) -> float | None:
    valid = [(value, weight) for value, weight in values if weight > 0]
    if not valid:
        return None

    total_weight = sum(weight for _, weight in valid)
    if total_weight <= 0:
        return None

    return sum(value * weight for value, weight in valid) / total_weight


def weighted_quantile(
    values: list[tuple[float, float]],
    quantile: float,
) -> float | None:
    valid = sorted(
        (value, weight)
        for value, weight in values
        if weight > 0
    )

    if not valid:
        return None

    total_weight = sum(weight for _, weight in valid)
    threshold = total_weight * min(max(quantile, 0), 1)
    cumulative = 0.0

    for value, weight in valid:
        cumulative += weight
        if cumulative >= threshold:
            return value

    return valid[-1][0]


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


def similarity_weight(
    row: dict[str, Any],
    target_dt: datetime,
    day_info: dict[str, Any],
) -> float:
    visit_date = row.get("visit_date")
    if not visit_date:
        return 0.0

    try:
        history_dt = datetime.strptime(str(visit_date), "%Y-%m-%d")
    except ValueError:
        return 0.0

    weight = 1.0

    # 曜日一致を最も強く評価する。
    if history_dt.weekday() == target_dt.weekday():
        weight *= 4.0
    elif (history_dt.weekday() >= 5) == (target_dt.weekday() >= 5):
        weight *= 1.8
    else:
        weight *= 0.75

    target_weather = normalize_weather(day_info.get("weather"))
    history_weather = normalize_weather(row.get("weather"))
    if target_weather and history_weather:
        weight *= 1.8 if target_weather == history_weather else 0.8

    target_price = day_info.get("ticket_price")
    history_price = row.get("ticket_price")
    try:
        if target_price is not None and history_price is not None:
            difference = abs(float(target_price) - float(history_price))
            weight *= max(0.55, 1.7 - difference / 2500)
    except (TypeError, ValueError):
        pass

    target_open = time_to_minutes(day_info.get("official_open_time"))
    history_open = time_to_minutes(row.get("official_open_time"))
    if target_open is not None and history_open is not None:
        difference = abs(target_open - history_open)
        weight *= max(0.6, 1.5 - difference / 180)

    # 遠すぎる過去データを少しだけ弱める。
    age_days = abs((target_dt.date() - history_dt.date()).days)
    weight *= max(0.65, 1.0 - age_days / 2500)

    return max(weight, 0.01)


def build_attraction_prediction(
    history_rows: list[dict[str, Any]],
    weighted_rows: list[tuple[dict[str, Any], float]],
    entry_minutes: int,
    code: str,
    name: str,
    sellout_field: str,
    limit_field: str,
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
    }


def mock_forecast(target_date: str, entry_time: str) -> dict[str, Any]:
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    weekend = dt.weekday() >= 5
    base = 58 if weekend else 36

    return {
        "date": target_date,
        "entry_time": entry_time,
        "crowd_label": "混雑" if weekend else "普通",
        "crowd_score": base,
        "weather": "データ未更新",
        "temperature_high": None,
        "temperature_low": None,
        "ticket_price": None,
        "recommended_level": 2 if weekend else 4,
        "data_status": "demo",
        "attractions": [
            {
                "attraction_code": "beauty",
                "name": "美女と野獣",
                "acquisition_probability": 54 if weekend else 78,
                "predicted_sellout_time": "12:40" if weekend else "15:20",
                "confidence_low": "11:30" if weekend else "13:50",
                "confidence_high": "14:10" if weekend else "17:10",
            },
            {
                "attraction_code": "baymax",
                "name": "ベイマックス",
                "acquisition_probability": 69 if weekend else 88,
                "predicted_sellout_time": "15:10" if weekend else "17:30",
                "confidence_low": "13:40" if weekend else "16:00",
                "confidence_high": "17:20" if weekend else "19:00",
            },
            {
                "attraction_code": "splash",
                "name": "スプラッシュ・マウンテン",
                "acquisition_probability": 87 if weekend else 96,
                "predicted_sellout_time": "18:20" if weekend else None,
                "confidence_low": "16:40" if weekend else None,
                "confidence_high": "記録上限",
            },
        ],
        "reasons": [
            "Supabase未接続のためデモ値を表示しています。",
            "接続後はPC側で作成した予測結果を読み込みます。",
        ],
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    return jsonify(
        {
            "supabase_connected": supabase_enabled(),
            "today": date.today().isoformat(),
        }
    )


@app.get("/api/forecast")
def api_forecast():
    target_date = request.args.get("date", "").strip()
    entry_time = request.args.get("entry_time", "10:00").strip()

    try:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        entry_dt = datetime.strptime(entry_time, "%H:%M")
    except ValueError:
        return jsonify(
            {
                "error": "日付または時刻の形式が正しくありません。",
            }
        ), 400

    if not supabase_enabled():
        return jsonify(mock_forecast(target_date, entry_time))

    try:
        # 選択日の天気・価格・開園時間などが登録済みなら、
        # 類似日の判定条件として利用する。
        day_rows = supabase_get(
            "daily_forecasts",
            {
                "select": "*",
                "target_date": f"eq.{target_date}",
                "limit": "1",
            },
        )
        day = day_rows[0] if day_rows else {}

        history_rows = supabase_get(
            "dpa_history_view",
            {
                "select": "*",
                "order": "visit_date.desc",
                "limit": "1000",
            },
        )

        if not history_rows:
            return jsonify(
                {
                    "error": "予測に使える実績データがありません。",
                    "data_status": "not_found",
                }
            ), 404

        weighted_rows = [
            (row, similarity_weight(row, target_dt, day))
            for row in history_rows
        ]
        weighted_rows = [
            item for item in weighted_rows
            if item[1] > 0
        ]
        weighted_rows.sort(key=lambda item: item[1], reverse=True)

        # 条件が近い上位120件を予測に利用する。
        selected_rows = weighted_rows[:120]

        entry_minutes = entry_dt.hour * 60 + entry_dt.minute

        attraction_specs = [
            (
                "beauty",
                "美女と野獣",
                "beauty_sellout_time",
                "beauty_is_limit",
            ),
            (
                "baymax",
                "ベイマックス",
                "baymax_sellout_time",
                "baymax_is_limit",
            ),
            (
                "splash",
                "スプラッシュ・マウンテン",
                "splash_sellout_time",
                "splash_is_limit",
            ),
        ]

        attractions = [
            build_attraction_prediction(
                history_rows,
                selected_rows,
                entry_minutes,
                code,
                name,
                sellout_field,
                limit_field,
            )
            for code, name, sellout_field, limit_field in attraction_specs
        ]

        crowd_values: list[tuple[float, float]] = []
        for row, weight in selected_rows:
            score = crowd_score_from_label(row.get("crowd_label"))
            if score is not None:
                crowd_values.append((float(score), weight))

        crowd_score_value = weighted_average(crowd_values)
        crowd_score = (
            int(round(crowd_score_value))
            if crowd_score_value is not None
            else None
        )
        crowd_label = crowd_label_from_score(crowd_score_value)

        probabilities = [
            int(item["acquisition_probability"])
            for item in attractions
            if item.get("sample_count", 0) > 0
        ]
        average_probability = (
            sum(probabilities) / len(probabilities)
            if probabilities
            else 0
        )

        if average_probability >= 85:
            recommended_level = 5
        elif average_probability >= 70:
            recommended_level = 4
        elif average_probability >= 55:
            recommended_level = 3
        elif average_probability >= 40:
            recommended_level = 2
        else:
            recommended_level = 1

        weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
        weekday_name = weekday_names[target_dt.weekday()]

        reasons = [
            f"登録済み実績{len(history_rows)}件から、条件が近い上位{len(selected_rows)}件を使って予測しました。",
            f"選択日は{weekday_name}曜日のため、同じ曜日の実績を強く評価しています。",
            f"入園予定時刻{entry_time}にDPAが残っていた実績の割合を取得予測率として表示しています。",
        ]

        used_conditions = []
        if day.get("weather"):
            used_conditions.append("天気")
        if day.get("ticket_price") is not None:
            used_conditions.append("チケット価格")
        if day.get("official_open_time"):
            used_conditions.append("開園時刻")

        if used_conditions:
            reasons.append(
                "類似日の判定には、" + "・".join(used_conditions) + "も利用しています。"
            )
        else:
            reasons.append(
                "選択日の天気・価格・開園時刻が未登録のため、主に曜日と過去実績から予測しています。"
            )

        return jsonify(
            {
                "date": target_date,
                "entry_time": entry_time,
                "crowd_label": day.get("crowd_label") or crowd_label,
                "crowd_score": day.get("crowd_score") or crowd_score,
                "weather": day.get("weather") or "予報未登録",
                "temperature_high": day.get("temperature_high"),
                "temperature_low": day.get("temperature_low"),
                "ticket_price": day.get("ticket_price"),
                "recommended_level": recommended_level,
                "attractions": attractions,
                "reasons": reasons,
                "data_status": "live",
                "prediction_method": "similar_history",
                "history_count": len(history_rows),
                "sample_count": len(selected_rows),
            }
        )

    except requests.RequestException as exc:
        return jsonify(
            {
                "error": f"Supabaseの取得に失敗しました: {exc}",
            }
        ), 502


@app.get("/api/analytics")
def api_analytics():
    if not supabase_enabled():
        return jsonify(
            {
                "data_status": "demo",
                "summary": {
                    "record_count": 0,
                    "latest_record_date": None,
                    "model_updated_at": None,
                },
                "weekday_stats": [],
                "remaining_rate_stats": [],
                "message": "Supabase接続後に分析結果が表示されます。",
            }
        )

    try:
        park_days = supabase_get(
            "park_days",
            {
                "select": (
                    "visit_date,"
                    "crowd_label,"
                    "weather,"
                    "ticket_price,"
                    "official_open_time"
                ),
                "order": "visit_date.desc",
            },
        )

        record_count = len(park_days)

        latest_record_date = None
        if park_days:
            latest_record_date = park_days[0].get("visit_date")

        weekday_counts: dict[str, int] = {
            "月": 0,
            "火": 0,
            "水": 0,
            "木": 0,
            "金": 0,
            "土": 0,
            "日": 0,
        }

        weekday_names = [
            "月",
            "火",
            "水",
            "木",
            "金",
            "土",
            "日",
        ]

        for row in park_days:
            visit_date = row.get("visit_date")

            if not visit_date:
                continue

            try:
                visit_dt = datetime.strptime(
                    visit_date,
                    "%Y-%m-%d",
                )
            except ValueError:
                continue

            weekday_name = weekday_names[visit_dt.weekday()]
            weekday_counts[weekday_name] += 1

        weekday_stats = [
            {
                "weekday": weekday_name,
                "record_count": weekday_counts[weekday_name],
            }
            for weekday_name in weekday_names
        ]

        return jsonify(
            {
                "data_status": "live",
                "summary": {
                    "record_count": record_count,
                    "latest_record_date": latest_record_date,
                    "model_updated_at": None,
                },
                "weekday_stats": weekday_stats,
                "remaining_rate_stats": [],
                "message": (
                    "実績データを取得しました。"
                    if record_count > 0
                    else "実績データはまだありません。"
                ),
            }
        )

    except requests.RequestException as exc:
        return jsonify(
            {
                "error": f"分析結果の取得に失敗しました: {exc}",
            }
        ), 502


@app.get("/api/database")
def api_database():
    try:
        page = max(
            int(request.args.get("page", "1")),
            1,
        )
        page_size = min(
            max(
                int(request.args.get("page_size", "20")),
                1,
            ),
            100,
        )
    except ValueError:
        return jsonify(
            {
                "error": "ページ番号または表示件数が正しくありません。",
            }
        ), 400

    offset = (page - 1) * page_size

    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    if not supabase_enabled():
        return jsonify(
            {
                "data_status": "demo",
                "records": [],
                "page": page,
                "page_size": page_size,
                "message": "Supabase接続後に実績データが表示されます。",
            }
        )

    params: dict[str, Any] = {
        "select": "*",
        "order": "visit_date.desc",
        "limit": str(page_size),
        "offset": str(offset),
    }

    conditions = []

    if date_from:
        conditions.append(f"visit_date.gte.{date_from}")

    if date_to:
        conditions.append(f"visit_date.lte.{date_to}")

    if conditions:
        params["and"] = f"({','.join(conditions)})"

    try:
        records = supabase_get(
            "dpa_history_view",
            params,
        )

        return jsonify(
            {
                "data_status": "live",
                "records": records,
                "page": page,
                "page_size": page_size,
            }
        )

    except requests.RequestException as exc:
        return jsonify(
            {
                "error": f"実績データの取得に失敗しました: {exc}",
            }
        ), 502


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=os.getenv("FLASK_DEBUG") == "1",
    )