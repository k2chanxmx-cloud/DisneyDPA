# Disney DPA Prediction API Ver4

既存Ver3の動作を保ったまま、機能別に分割したRender向け構成です。

## Render環境変数
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`（学習ログ保存に推奨）

## 起動
```bash
pip install -r requirements.txt
gunicorn app:app
```

## 確認URL
- `/api/status`
- `/api/forecast?date=2026-08-15&entry_time=10:00`

JSONに `version: 4.0.0` と `build: modular-yosocal-learning` が出れば切替成功です。

## Ver4.1.0 changes

- Moved shared labels and attraction definitions to `constants.py`.
- Fixed the missing `YOSOCAL_EVENT_TYPE_LABELS` definition.
- Removed HTML tags from Yosocal event and closure names.
- Yosocal/official source parser failures are recorded in `source_diagnostics` instead of crashing `/api/forecast`.
- Unexpected forecast errors now return a JSON error response containing `version`, `build`, `error_type`, and `error_detail` rather than Flask's HTML 500 page.
- Prediction-log write failures no longer discard an otherwise successful forecast.
