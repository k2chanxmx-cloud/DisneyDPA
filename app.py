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


def supabase_get(table: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
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
                "confidence_high": "記録上限" if weekend else "記録上限",
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
    return jsonify({
        "supabase_connected": supabase_enabled(),
        "today": date.today().isoformat(),
    })


@app.get("/api/forecast")
def api_forecast():
    target_date = request.args.get("date", "").strip()
    entry_time = request.args.get("entry_time", "10:00").strip()

    try:
        datetime.strptime(target_date, "%Y-%m-%d")
        datetime.strptime(entry_time, "%H:%M")
    except ValueError:
        return jsonify({"error": "日付または時刻の形式が正しくありません。"}), 400

    if not supabase_enabled():
        return jsonify(mock_forecast(target_date, entry_time))

    try:
        prediction_rows = supabase_get(
            "daily_predictions",
            {
                "select": "*",
                "target_date": f"eq.{target_date}",
                "entry_time": f"eq.{entry_time}:00",
                "order": "attraction_code.asc",
            },
        )

        day_rows = supabase_get(
            "daily_forecasts",
            {
                "select": "*",
                "target_date": f"eq.{target_date}",
                "limit": "1",
            },
        )

        if not prediction_rows:
            return jsonify({
                "error": "この日付・入園時刻の予測データはまだありません。",
                "data_status": "not_found",
            }), 404

        day = day_rows[0] if day_rows else {}
        attraction_names = {
            "beauty": "美女と野獣",
            "baymax": "ベイマックス",
            "splash": "スプラッシュ・マウンテン",
        }

        attractions = []
        for row in prediction_rows:
            attractions.append({
                "attraction_code": row.get("attraction_code"),
                "name": attraction_names.get(row.get("attraction_code"), row.get("attraction_code")),
                "acquisition_probability": row.get("acquisition_probability"),
                "predicted_sellout_time": row.get("predicted_sellout_time"),
                "confidence_low": row.get("confidence_low"),
                "confidence_high": row.get("confidence_high"),
            })

        reasons = day.get("prediction_reasons") or []
        return jsonify({
            "date": target_date,
            "entry_time": entry_time,
            "crowd_label": day.get("crowd_label"),
            "crowd_score": day.get("crowd_score"),
            "weather": day.get("weather"),
            "temperature_high": day.get("temperature_high"),
            "temperature_low": day.get("temperature_low"),
            "ticket_price": day.get("ticket_price"),
            "recommended_level": day.get("recommended_level"),
            "attractions": attractions,
            "reasons": reasons,
            "data_status": "live",
        })
    except requests.RequestException as exc:
        return jsonify({"error": f"Supabaseの取得に失敗しました: {exc}"}), 502


@app.get("/api/analytics")
def api_analytics():
    if not supabase_enabled():
        return jsonify({
            "data_status": "demo",
            "summary": {
                "record_count": 0,
                "latest_record_date": None,
                "model_updated_at": None,
            },
            "weekday_stats": [],
            "remaining_rate_stats": [],
            "message": "Supabase接続後に分析結果が表示されます。",
        })

    try:
        summaries = supabase_get(
            "analysis_summaries",
            {
                "select": "*",
                "order": "sort_order.asc",
            },
        )
        metrics = supabase_get(
            "analysis_metrics",
            {
                "select": "*",
                "order": "metric_group.asc,sort_order.asc",
            },
        )
        return jsonify({
            "data_status": "live",
            "summaries": summaries,
            "metrics": metrics,
        })
    except requests.RequestException as exc:
        return jsonify({"error": f"分析結果の取得に失敗しました: {exc}"}), 502


@app.get("/api/database")
def api_database():
    page = max(int(request.args.get("page", "1")), 1)
    page_size = min(max(int(request.args.get("page_size", "20")), 1), 100)
    offset = (page - 1) * page_size
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    if not supabase_enabled():
        return jsonify({
            "data_status": "demo",
            "records": [],
            "page": page,
            "page_size": page_size,
            "message": "Supabase接続後に実績データが表示されます。",
        })

    params: dict[str, Any] = {
        "select": "*",
        "order": "visit_date.desc",
        "limit": str(page_size),
        "offset": str(offset),
    }
    if date_from:
        params["visit_date"] = f"gte.{date_from}"
    if date_to:
        # PostgRESTで同一列に複数条件を付けるためandを利用
        current = params.pop("visit_date", None)
        conditions = []
        if current:
            conditions.append(f"visit_date.{current}")
        conditions.append(f"visit_date.lte.{date_to}")
        params["and"] = f"({','.join(conditions)})"

    try:
        records = supabase_get("dpa_history_view", params)
        return jsonify({
            "data_status": "live",
            "records": records,
            "page": page,
            "page_size": page_size,
        })
    except requests.RequestException as exc:
        return jsonify({"error": f"実績データの取得に失敗しました: {exc}"}), 502


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
