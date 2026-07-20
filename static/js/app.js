const state = {
  currentPage: 1,
  analyticsLoaded: false,
  databaseLoaded: false,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateJa(value) {
  if (!value) return "—";
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric", month: "long", day: "numeric", weekday: "short"
  }).format(date);
}

function stars(level) {
  const n = Math.min(Math.max(Number(level || 0), 0), 5);
  return "★".repeat(n) + "☆".repeat(5 - n);
}

async function fetchJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "読み込みに失敗しました。");
  return data;
}

async function loadStatus() {
  try {
    const data = await fetchJson("/api/status");
    const badge = $("connectionBadge");
    badge.textContent = data.supabase_connected ? "DB接続中" : "デモ表示";
    badge.style.color = data.supabase_connected ? "var(--success)" : "var(--gold)";
    if (!$("targetDate").value) $("targetDate").value = data.today;
  } catch {
    $("connectionBadge").textContent = "接続エラー";
  }
}

function setupNavigation() {
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.addEventListener("click", async () => {
      document.querySelectorAll(".nav-button").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
      button.classList.add("active");
      $(button.dataset.screen).classList.add("active");

      if (button.dataset.screen === "analyticsScreen" && !state.analyticsLoaded) {
        await loadAnalytics();
      }
      if (button.dataset.screen === "databaseScreen" && !state.databaseLoaded) {
        await loadDatabase();
      }
    });
  });
}

async function loadForecast() {
  const date = $("targetDate").value;
  const entryTime = $("entryTime").value || "10:00";
  if (!date) {
    alert("来園予定日を選択してください。");
    return;
  }

  $("forecastButton").disabled = true;
  $("forecastButton").textContent = "予測を読み込み中…";

  try {
    const data = await fetchJson(`/api/forecast?date=${encodeURIComponent(date)}&entry_time=${encodeURIComponent(entryTime)}`);
    $("forecastEmpty").classList.add("hidden");
    $("forecastResult").classList.remove("hidden");

    $("daySummary").innerHTML = `
      <div class="summary-top">
        <div>
          <div class="summary-date">${escapeHtml(formatDateJa(data.date))}</div>
          <div class="demo-note">${data.data_status === "demo" ? "現在はデモデータです" : "更新済み予測データ"}</div>
        </div>
        <div class="stars">${stars(data.recommended_level)}</div>
      </div>
      <div class="summary-grid">
        <div class="summary-item"><small>混雑予測</small><strong>${escapeHtml(data.crowd_label || "—")}</strong></div>
        <div class="summary-item"><small>混雑指数</small><strong>${escapeHtml(data.crowd_score ?? "—")}</strong></div>
        <div class="summary-item"><small>天気</small><strong>${escapeHtml(data.weather || "—")}</strong></div>
        <div class="summary-item"><small>最高 / 最低</small><strong>${escapeHtml(data.temperature_high ?? "—")}℃ / ${escapeHtml(data.temperature_low ?? "—")}℃</strong></div>
        <div class="summary-item"><small>チケット価格</small><strong>${data.ticket_price ? `${Number(data.ticket_price).toLocaleString()}円` : "—"}</strong></div>
        <div class="summary-item"><small>入園予定</small><strong>${escapeHtml(data.entry_time)}</strong></div>
      </div>
    `;

    $("attractionCards").innerHTML = (data.attractions || []).map((item) => {
      const probability = Number(item.acquisition_probability || 0);
      const range = item.confidence_low || item.confidence_high
        ? `${item.confidence_low || "—"} ～ ${item.confidence_high || "—"}`
        : "—";
      return `
        <article class="attraction-card">
          <div class="attraction-header">
            <h3>${escapeHtml(item.name)}</h3>
            <div class="probability">${probability}%</div>
          </div>
          <div class="progress"><span style="width:${Math.min(Math.max(probability, 0), 100)}%"></span></div>
          <div class="detail-row"><span>DPA取得予測率</span><strong>${probability}%</strong></div>
          <div class="detail-row"><span>売り切れ予測</span><strong>${escapeHtml(item.predicted_sellout_time || "記録上限まで残る予測")}</strong></div>
          <div class="detail-row"><span>予測範囲</span><strong>${escapeHtml(range)}</strong></div>
        </article>
      `;
    }).join("");

    $("reasonList").innerHTML = (data.reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");
  } catch (error) {
    $("forecastEmpty").classList.remove("hidden");
    $("forecastResult").classList.add("hidden");
    $("forecastEmpty").innerHTML = `<span class="error-text">${escapeHtml(error.message)}</span>`;
  } finally {
    $("forecastButton").disabled = false;
    $("forecastButton").textContent = "この日の予測を見る";
  }
}

async function loadAnalytics() {
  const container = $("analyticsContent");
  try {
    const data = await fetchJson("/api/analytics");
    state.analyticsLoaded = true;

    if (data.data_status === "demo") {
      container.innerHTML = `<div class="empty-card">${escapeHtml(data.message)}</div>`;
      return;
    }

    const summaries = data.summaries || [];
    const metrics = data.metrics || [];
    const cards = [];

    for (const item of summaries) {
      cards.push(`
        <article class="metric-card">
          <div class="metric-title">${escapeHtml(item.title)}</div>
          <div class="metric-value">${escapeHtml(item.value_text || "—")}</div>
          <div class="metric-note">${escapeHtml(item.description || "")}</div>
        </article>
      `);
    }

    for (const item of metrics) {
      cards.push(`
        <article class="metric-card">
          <div class="metric-title">${escapeHtml(item.metric_label)}</div>
          <div class="metric-value">${escapeHtml(item.value_text || item.value_number || "—")}</div>
          <div class="metric-note">${escapeHtml(item.note || "")}</div>
        </article>
      `);
    }

    container.innerHTML = cards.length
      ? cards.join("")
      : `<div class="empty-card">分析結果はまだ登録されていません。</div>`;
  } catch (error) {
    container.innerHTML = `<div class="empty-card error-text">${escapeHtml(error.message)}</div>`;
  }
}

function formatSellout(time, isLimit) {
  if (isLimit) return `${time || ""}${time ? " " : ""}（記録上限）`;
  return time || "—";
}

async function loadDatabase(page = 1) {
  const container = $("databaseContent");
  const params = new URLSearchParams({
    page: String(page),
    page_size: "20",
  });
  if ($("dbDateFrom").value) params.set("date_from", $("dbDateFrom").value);
  if ($("dbDateTo").value) params.set("date_to", $("dbDateTo").value);

  try {
    const data = await fetchJson(`/api/database?${params.toString()}`);
    state.currentPage = page;
    state.databaseLoaded = true;
    $("pageLabel").textContent = `${page}ページ`;

    if (data.data_status === "demo") {
      container.innerHTML = `<div class="empty-card">${escapeHtml(data.message)}</div>`;
      return;
    }

    const records = data.records || [];
    container.innerHTML = records.length ? records.map((row) => `
      <article class="record-card">
        <div class="record-date">${escapeHtml(formatDateJa(row.visit_date))}</div>
        <div class="record-grid">
          <div><small>混雑</small><strong>${escapeHtml(row.crowd_label || "—")}</strong></div>
          <div><small>天気</small><strong>${escapeHtml(row.weather || "—")}</strong></div>
          <div><small>気温</small><strong>${escapeHtml(row.temperature_high ?? "—")}℃ / ${escapeHtml(row.temperature_low ?? "—")}℃</strong></div>
          <div><small>価格</small><strong>${row.ticket_price ? `${Number(row.ticket_price).toLocaleString()}円` : "—"}</strong></div>
          <div><small>開園</small><strong>${escapeHtml(row.official_open_time || "—")}</strong></div>
          <div><small>データ元</small><strong>${escapeHtml(row.source_type || "—")}</strong></div>
        </div>
        <div class="dpa-lines">
          <div class="dpa-line"><span>美女と野獣</span><strong>${escapeHtml(formatSellout(row.beauty_sellout_time, row.beauty_is_limit))}</strong></div>
          <div class="dpa-line"><span>ベイマックス</span><strong>${escapeHtml(formatSellout(row.baymax_sellout_time, row.baymax_is_limit))}</strong></div>
          <div class="dpa-line"><span>スプラッシュ</span><strong>${escapeHtml(formatSellout(row.splash_sellout_time, row.splash_is_limit))}</strong></div>
        </div>
      </article>
    `).join("") : `<div class="empty-card">該当するデータはありません。</div>`;
  } catch (error) {
    container.innerHTML = `<div class="empty-card error-text">${escapeHtml(error.message)}</div>`;
  }
}

$("forecastButton").addEventListener("click", loadForecast);
$("dbSearchButton").addEventListener("click", () => loadDatabase(1));
$("prevPageButton").addEventListener("click", () => {
  if (state.currentPage > 1) loadDatabase(state.currentPage - 1);
});
$("nextPageButton").addEventListener("click", () => loadDatabase(state.currentPage + 1));

setupNavigation();
loadStatus();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/static/service-worker.js"));
}
