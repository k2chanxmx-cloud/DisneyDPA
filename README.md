# Disney DPA Prediction API Ver4.1.1 Complete

Renderへそのまま配置できる、APIとWeb画面を含む完全版です。

## 含まれるもの
- Flask API
- `templates/index.html`
- `static/css/style.css`
- `static/js/app.js`
- favicon
- Supabase接続
- Yosocal取得
- 予測ログ・自己学習
- Render設定

## Render環境変数
- `APP_ENV`：開発は `development`、本番は `production`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`（予測ログ保存に推奨）
- `REQUEST_TIMEOUT`（任意、既定15秒）

## Render設定
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`

## URL
- `/` Web画面
- `/api/status` 状態確認
- `/api/forecast?date=2026-08-15&entry_time=10:00` 予測JSON
- `/api/analytics` 分析JSON
- `/api/database` 実績JSON

## 配置時の注意
ZIP内のファイル・フォルダを、GitHubリポジトリ直下へ置いてください。`templates` と `static` を削除しないでください。

## Ver5.0.1

- 類似日判定を掛け算式から100点式の特徴量スコアへ変更
- 曜日、学校休暇傾向、季節イベント期、天気、気温、開園時刻、価格、データ鮮度を評価
- `/api/forecast` に上位10件の `similar_days` とスコア内訳を追加
- 既存の上位120件による加重予測、学習補正、API項目との互換性を維持


## Ver5.0.2

- 美女と野獣・ベイマックス・スプラッシュごとの特徴量ウェイトを追加
- 80点→75点→70点の段階的な類似度基準を追加
- 基準を満たす履歴が少ない場合は上位50件を自動採用
- 最大採用件数は120件
- APIにプロファイル、重み、採用件数、最低類似度、採用方式を追加

## Ver5.0.3 予測精度ダッシュボード

- `/accuracy` に予測精度レポートを追加
- `/api/accuracy` に精度集計APIを追加
- アトラクション別の平均絶対誤差、平均バイアス、15/30/60分以内率を表示
- 入園時刻時点の取得可否について、正解率・Brier Score・確率バイアスを集計
- 過去日の未評価ログを実績データと自動照合
- 評価データがまだない場合もエラーにせず案内を表示


## Ver6.0.0 Adaptive Bias Correction

- アトラクション別に予測時刻と実績時刻の平均誤差を算出
- 評価件数に応じて 0% / 20% / 50% / 75% / 100% の段階適用
- 時刻補正は最大 ±60分、学習平均は最大 ±90分に制限
- APIに raw_prediction / bias_minutes / bias_apply_rate / bias_applied_minutes / corrected_prediction / bias_reason を追加
- 取得確率も同じ段階方式で最大 ±15ポイントの範囲内で補正

評価が10件未満の間は、診断値のみ返して予測値は変更しません。

## Ver6.1.0 Adaptive Feature Learning

評価済み予測が10件以上たまると、各アトラクションについて「特徴一致度が高いほど予測誤差が小さくなるか」を分析し、曜日・休暇・季節イベント・天気・気温・開園時刻・価格・鮮度の重みを自動調整します。

- 10件未満: 学習を適用しない
- 10〜99件: 件数に応じて段階的に適用
- 100件以上: 学習強度100%
- 1回の変更幅: 各基準重みの±20%以内
- 重み合計: 常に100点へ正規化
- API: `feature_learning` に基準重み、学習後重み、変化量、相関、件数を出力

Bias補正（Ver6.0）も引き続き併用します。
