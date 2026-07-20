# Disneyland DPA Forecast 初期版

PC側で更新したSupabaseデータを、スマホPWAで閲覧するための初期版です。

## 収録画面

1. 日付予測
2. 分析結果情報
3. 分析情報データベース

スマホ側は閲覧専用です。実績登録・OCR修正・再学習は今後作成するPC管理アプリで行います。

## 1. Supabaseの準備

1. Supabaseで新規プロジェクトを作成
2. SQL Editorを開く
3. `sql/schema.sql` の全文を実行
4. Project Settings → API から以下を確認
   - Project URL
   - anon public key

`service_role` キーはPC管理アプリ専用です。Renderやブラウザへ直接置かないでください。

## 2. ローカル起動

`.env.example` を参考に環境変数を設定します。

Windowsでは `起動.bat` をダブルクリックできます。

環境変数を未設定でも起動でき、その場合は日付予測画面にデモ値が出ます。

## 3. Renderへの公開

このフォルダをGitHubへアップロードし、RenderでBlueprintまたはWeb Serviceを作成します。

RenderのEnvironmentへ登録:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`

`render.yaml` を同梱しています。

## 4. PWAとしてホーム画面へ追加

### iPhone
Safariで開く → 共有 → ホーム画面に追加

### Android
Chromeで開く → メニュー → アプリをインストール

## 5. 予測データの時刻形式

スマホ側は `daily_predictions.entry_time` を30分刻みで検索します。

例:

- 09:00
- 09:30
- 10:00
- 10:30

PC管理アプリでは、対象日ごと・入園時刻ごと・アトラクションごとに予測結果を保存します。

## 6. 次段階

次はPC管理アプリを追加します。

- CSV手入力・編集
- Supabaseアップロード
- DPA画像の登録
- OCR結果確認
- 分析集計
- 未来日の予測結果生成
