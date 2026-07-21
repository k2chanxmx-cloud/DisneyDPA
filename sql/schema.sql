-- =========================================================
-- Disneyland DPA Forecast 初期テーブル
-- Supabase SQL Editor に貼り付けて実行してください。
-- =========================================================

create extension if not exists pgcrypto;

-- 1. 1日単位の基本情報
create table if not exists public.park_days (
  id uuid primary key default gen_random_uuid(),
  visit_date date not null unique,
  weekday_no smallint generated always as (extract(isodow from visit_date)::smallint) stored,
  weather text,
  temperature_high numeric(4,1),
  temperature_low numeric(4,1),
  ticket_price integer,
  crowd_label text,
  crowd_score numeric(5,2),
  official_open_time time,
  actual_open_time time,
  is_holiday boolean not null default false,
  holiday_type text,
  event_tags text[] not null default '{}',
  source_type text,
  source_url text,
  source_image_path text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 2. アトラクション別のDPA売り切れ実績
create table if not exists public.dpa_history (
  id uuid primary key default gen_random_uuid(),
  park_day_id uuid not null references public.park_days(id) on delete cascade,
  attraction_code text not null check (attraction_code in ('beauty','baymax','splash')),
  sellout_time time,
  is_limit boolean not null default false,
  observation_limit_time time,
  raw_ocr_text text,
  manually_verified boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (park_day_id, attraction_code)
);

-- 3. 未来日の混雑・天気・価格など
create table if not exists public.daily_forecasts (
  id uuid primary key default gen_random_uuid(),
  target_date date not null unique,
  crowd_label text,
  crowd_score numeric(5,2),
  weather text,
  temperature_high numeric(4,1),
  temperature_low numeric(4,1),
  ticket_price integer,
  recommended_level smallint check (recommended_level between 0 and 5),
  prediction_reasons jsonb not null default '[]'::jsonb,
  source_updated_at timestamptz,
  model_version text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 4. 入園予定時刻×アトラクション別の予測結果
create table if not exists public.daily_predictions (
  id uuid primary key default gen_random_uuid(),
  target_date date not null,
  entry_time time not null,
  attraction_code text not null check (attraction_code in ('beauty','baymax','splash')),
  acquisition_probability numeric(5,2) not null check (acquisition_probability between 0 and 100),
  predicted_sellout_time time,
  predicted_limit_probability numeric(5,2) check (predicted_limit_probability between 0 and 100),
  confidence_low time,
  confidence_high time,
  model_version text,
  calculated_at timestamptz not null default now(),
  unique (target_date, entry_time, attraction_code)
);

-- 5. 分析画面上部の要約カード
create table if not exists public.analysis_summaries (
  id uuid primary key default gen_random_uuid(),
  summary_key text not null unique,
  title text not null,
  value_text text,
  description text,
  sort_order integer not null default 0,
  updated_at timestamptz not null default now()
);

-- 6. 曜日別、時間別残存率などの汎用分析指標
create table if not exists public.analysis_metrics (
  id uuid primary key default gen_random_uuid(),
  metric_group text not null,
  metric_key text not null,
  metric_label text not null,
  attraction_code text,
  category text,
  value_number numeric,
  value_text text,
  unit text,
  note text,
  sort_order integer not null default 0,
  updated_at timestamptz not null default now(),
  unique (metric_group, metric_key, attraction_code, category)
);

-- スマホ閲覧用ビュー
create or replace view public.dpa_history_view as
select
  p.visit_date,
  p.weather,
  p.temperature_high,
  p.temperature_low,
  p.ticket_price,
  p.crowd_label,
  p.crowd_score,
  p.official_open_time,
  p.actual_open_time,
  p.is_holiday,
  p.holiday_type,
  p.source_type,
  max(d.sellout_time) filter (where d.attraction_code = 'beauty') as beauty_sellout_time,
  bool_or(d.is_limit) filter (where d.attraction_code = 'beauty') as beauty_is_limit,
  max(d.sellout_time) filter (where d.attraction_code = 'baymax') as baymax_sellout_time,
  bool_or(d.is_limit) filter (where d.attraction_code = 'baymax') as baymax_is_limit,
  max(d.sellout_time) filter (where d.attraction_code = 'splash') as splash_sellout_time,
  bool_or(d.is_limit) filter (where d.attraction_code = 'splash') as splash_is_limit
from public.park_days p
left join public.dpa_history d on d.park_day_id = p.id
group by p.id;

-- updated_at 自動更新
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_park_days_updated_at on public.park_days;
create trigger trg_park_days_updated_at
before update on public.park_days
for each row execute function public.set_updated_at();

drop trigger if exists trg_dpa_history_updated_at on public.dpa_history;
create trigger trg_dpa_history_updated_at
before update on public.dpa_history
for each row execute function public.set_updated_at();

drop trigger if exists trg_daily_forecasts_updated_at on public.daily_forecasts;
create trigger trg_daily_forecasts_updated_at
before update on public.daily_forecasts
for each row execute function public.set_updated_at();

-- RLS
alter table public.park_days enable row level security;
alter table public.dpa_history enable row level security;
alter table public.daily_forecasts enable row level security;
alter table public.daily_predictions enable row level security;
alter table public.analysis_summaries enable row level security;
alter table public.analysis_metrics enable row level security;

-- スマホのanonキーは閲覧のみ
drop policy if exists "anon read park_days" on public.park_days;
create policy "anon read park_days"
on public.park_days for select
to anon
using (true);

drop policy if exists "anon read dpa_history" on public.dpa_history;
create policy "anon read dpa_history"
on public.dpa_history for select
to anon
using (true);

drop policy if exists "anon read daily_forecasts" on public.daily_forecasts;
create policy "anon read daily_forecasts"
on public.daily_forecasts for select
to anon
using (true);

drop policy if exists "anon read daily_predictions" on public.daily_predictions;
create policy "anon read daily_predictions"
on public.daily_predictions for select
to anon
using (true);

drop policy if exists "anon read analysis_summaries" on public.analysis_summaries;
create policy "anon read analysis_summaries"
on public.analysis_summaries for select
to anon
using (true);

drop policy if exists "anon read analysis_metrics" on public.analysis_metrics;
create policy "anon read analysis_metrics"
on public.analysis_metrics for select
to anon
using (true);

-- ビューの読み取り許可
grant select on public.dpa_history_view to anon, authenticated;

-- PC管理アプリからの書き込みは service_role キーで実行してください。
-- service_role キーは絶対にスマホ側・ブラウザ側へ置かないでください。

-- 初期サンプル
insert into public.analysis_summaries
(summary_key, title, value_text, description, sort_order)
values
('record_count', '登録実績数', '0日', 'PC管理アプリから取り込んだ実績件数です。', 1),
('latest_date', '最新実績日', '未登録', '最後に登録された実績日です。', 2),
('model_version', '予測モデル', '未学習', 'PC側で学習したモデルのバージョンです。', 3)
on conflict (summary_key) do nothing;
