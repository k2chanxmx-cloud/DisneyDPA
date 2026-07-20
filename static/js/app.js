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

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function stars(level) {
  const n = Math.min(Math.max(Number(level || 0), 0), 5);
  return "★".repeat(n) + "☆".repeat(5 - n);
}

async function fetchJson(url) {
  const separator = url.includes("?") ? "&" : "?";
  const cacheBustUrl = `${url}${separator}_=${Date.now()}`;

  const response = await fetch(cacheBustUrl, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
    },
  });

  let data;

  try {
    data = await response.json();
  } catch {
    throw new Error("サーバーから正しいデータを取得できませんでした。");
  }

  if (!response.ok) {
    throw new Error(data.error || "読み込みに失敗しました。");
  }

  return data;
}

async function loadStatus() {
  try {
    const data = await fetchJson("/api/status");
    const badge = $("connectionBadge");

    badge.textContent = data.supabase_connected
      ? "DB接続中"
      : "デモ表示";

    badge.style.color = data.supabase_connected
      ? "var(--success)"
      : "var(--gold)";

    if (!$("targetDate").value) {
      $("targetDate").value = data.today;
    }
  } catch (error) {
    console.error("接続状態の取得に失敗しました。", error);
    $("connectionBadge").textContent = "接続エラー";
  }
}

function setupNavigation() {
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.addEventListener("click", async () => {
      document.querySelectorAll(".nav-button").forEach((item) => {
        item.classList.remove("active");
      });

      document.querySelectorAll(".screen").forEach((screen) => {
        screen.classList.remove("active");
      });

      button.classList.add("active");

      const targetScreen = $(button.dataset.screen);

      if (targetScreen) {
        targetScreen.classList.add("active");
      }

      if (
        button.dataset.screen === "analyticsScreen" &&
        !state.analyticsLoaded
      ) {
        await loadAnalytics();
      }

      if (
        button.dataset.screen === "databaseScreen" &&
        !state.databaseLoaded
      ) {
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
    const params = new URLSearchParams({
      date,
      entry_time: entryTime,
    });

    const data = await fetchJson(
      `/api/forecast?${params.toString()}`
    );

    $("forecastEmpty").classList.add("hidden");
    $("forecastResult").classList.remove("hidden");

    $("daySummary").innerHTML = `
      <div class="summary-top">
        <div>
          <div class="summary-date">
            ${escapeHtml(formatDateJa(data.date))}
          </div>
          <div class="demo-note">
            ${
              data.data_status === "demo"
                ? "現在はデモデータです"
                : "更新済み予測データ"
            }
          </div>
        </div>
        <div class="stars">
          ${stars(data.recommended_level)}
        </div>
      </div>

      <div class="summary-grid">
        <div class="summary-item">
          <small>混雑予測</small>
          <strong>${escapeHtml(data.crowd_label || "—")}</strong>
        </div>

        <div class="summary-item">
          <small>混雑指数</small>
          <strong>${escapeHtml(data.crowd_score ?? "—")}</strong>
        </div>

        <div class="summary-item">
          <small>天気</small>
          <strong>${escapeHtml(data.weather || "—")}</strong>
        </div>

        <div class="summary-item">
          <small>最高 / 最低</small>
          <strong>
            ${escapeHtml(data.temperature_high ?? "—")}℃
            /
            ${escapeHtml(data.temperature_low ?? "—")}℃
          </strong>
        </div>

        <div class="summary-item">
          <small>チケット価格</small>
          <strong>
            ${
              data.ticket_price
                ? `${Number(data.ticket_price).toLocaleString()}円`
                : "—"
            }
          </strong>
        </div>

        <div class="summary-item">
          <small>入園予定</small>
          <strong>${escapeHtml(data.entry_time || entryTime)}</strong>
        </div>
      </div>
    `;

    const attractions = data.attractions || [];

    $("attractionCards").innerHTML = attractions.length
      ? attractions
          .map((item) => {
            const probability = Number(
              item.acquisition_probability || 0
            );

            const safeProbability = Math.min(
              Math.max(probability, 0),
              100
            );

            const range =
              item.confidence_low || item.confidence_high
                ? `${item.confidence_low || "—"} ～ ${
                    item.confidence_high || "—"
                  }`
                : "—";

            return `
              <article class="attraction-card">
                <div class="attraction-header">
                  <h3>${escapeHtml(item.name || "名称未登録")}</h3>
                  <div class="probability">
                    ${escapeHtml(probability)}%
                  </div>
                </div>

                <div class="progress">
                  <span style="width:${safeProbability}%"></span>
                </div>

                <div class="detail-row">
                  <span>DPA取得予測率</span>
                  <strong>${escapeHtml(probability)}%</strong>
                </div>

                <div class="detail-row">
                  <span>売り切れ予測</span>
                  <strong>
                    ${escapeHtml(
                      item.predicted_sellout_time ||
                        "記録上限まで残る予測"
                    )}
                  </strong>
                </div>

                <div class="detail-row">
                  <span>予測範囲</span>
                  <strong>${escapeHtml(range)}</strong>
                </div>
              </article>
            `;
          })
          .join("")
      : `
        <div class="empty-card">
          アトラクション別の予測はありません。
        </div>
      `;

    const reasons = data.reasons || [];

    $("reasonList").innerHTML = reasons.length
      ? reasons
          .map((reason) => {
            return `<li>${escapeHtml(reason)}</li>`;
          })
          .join("")
      : `<li>予測理由はまだ登録されていません。</li>`;
  } catch (error) {
    console.error("予測の取得に失敗しました。", error);

    $("forecastEmpty").classList.remove("hidden");
    $("forecastResult").classList.add("hidden");

    $("forecastEmpty").innerHTML = `
      <span class="error-text">
        ${escapeHtml(error.message)}
      </span>
    `;
  } finally {
    $("forecastButton").disabled = false;
    $("forecastButton").textContent = "この日の予測を見る";
  }
}

async function loadAnalytics() {
  const container = $("analyticsContent");

  container.innerHTML = `
    <div class="empty-card">
      分析結果を読み込み中です。
    </div>
  `;

  try {
    const data = await fetchJson("/api/analytics");
    state.analyticsLoaded = true;

    if (data.data_status === "demo") {
      container.innerHTML = `
        <div class="empty-card">
          ${escapeHtml(
            data.message ||
              "Supabase接続後に分析結果が表示されます。"
          )}
        </div>
      `;
      return;
    }

    const summary = data.summary || {};
    const weekdayStats = data.weekday_stats || [];
    const remainingRateStats =
      data.remaining_rate_stats || [];

    const recordCount = Number(summary.record_count || 0);

    const latestRecordDate = summary.latest_record_date
      ? formatDateJa(summary.latest_record_date)
      : "未登録";

    const modelUpdatedAt = summary.model_updated_at
      ? formatDateJa(summary.model_updated_at)
      : "未学習";

    const cards = [];

    cards.push(`
      <article class="metric-card">
        <div class="metric-title">
          登録実績数
        </div>
        <div class="metric-value">
          ${escapeHtml(recordCount)}件
        </div>
        <div class="metric-note">
          PC管理アプリから取り込んだ実績件数です。
        </div>
      </article>
    `);

    cards.push(`
      <article class="metric-card">
        <div class="metric-title">
          最新実績日
        </div>
        <div class="metric-value">
          ${escapeHtml(latestRecordDate)}
        </div>
        <div class="metric-note">
          最後に登録された実績日です。
        </div>
      </article>
    `);

    cards.push(`
      <article class="metric-card">
        <div class="metric-title">
          予測モデル
        </div>
        <div class="metric-value">
          ${escapeHtml(modelUpdatedAt)}
        </div>
        <div class="metric-note">
          PC側で学習したモデルの更新情報です。
        </div>
      </article>
    `);

    if (weekdayStats.length > 0) {
      const weekdayRows = weekdayStats
        .map((item) => {
          const weekday = item.weekday || "—";
          const count = Number(item.record_count || 0);

          return `
            <div class="detail-row">
              <span>
                ${escapeHtml(weekday)}曜日
              </span>
              <strong>
                ${escapeHtml(count)}件
              </strong>
            </div>
          `;
        })
        .join("");

      cards.push(`
        <article class="metric-card">
          <div class="metric-title">
            曜日別の登録件数
          </div>
          <div class="metric-note">
            登録済み実績を曜日ごとに集計しています。
          </div>
          <div class="dpa-lines">
            ${weekdayRows}
          </div>
        </article>
      `);
    }

    if (remainingRateStats.length > 0) {
      const remainingRows = remainingRateStats
        .map((item) => {
          const label =
            item.label ||
            item.attraction_name ||
            item.name ||
            "項目";

          const value =
            item.value_text ??
            item.value_number ??
            item.rate ??
            "—";

          return `
            <div class="detail-row">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `;
        })
        .join("");

      cards.push(`
        <article class="metric-card">
          <div class="metric-title">
            DPA残存率の傾向
          </div>
          <div class="metric-note">
            登録データから算出したDPAの傾向です。
          </div>
          <div class="dpa-lines">
            ${remainingRows}
          </div>
        </article>
      `);
    }

    container.innerHTML = cards.join("");
  } catch (error) {
    state.analyticsLoaded = false;

    console.error("分析結果の取得に失敗しました。", error);

    container.innerHTML = `
      <div class="empty-card error-text">
        ${escapeHtml(error.message)}
      </div>
    `;
  }
}

function formatSellout(time, isLimit) {
  if (isLimit) {
    return `${time || ""}${time ? " " : ""}（記録上限）`;
  }

  return time || "—";
}

async function loadDatabase(page = 1) {
  const container = $("databaseContent");

  container.innerHTML = `
    <div class="empty-card">
      データベースを読み込み中です。
    </div>
  `;

  const params = new URLSearchParams({
    page: String(page),
    page_size: "20",
  });

  if ($("dbDateFrom").value) {
    params.set("date_from", $("dbDateFrom").value);
  }

  if ($("dbDateTo").value) {
    params.set("date_to", $("dbDateTo").value);
  }

  try {
    const data = await fetchJson(
      `/api/database?${params.toString()}`
    );

    state.currentPage = page;
    state.databaseLoaded = true;

    $("pageLabel").textContent = `${page}ページ`;

    if (data.data_status === "demo") {
      container.innerHTML = `
        <div class="empty-card">
          ${escapeHtml(data.message)}
        </div>
      `;
      return;
    }

    const records = data.records || [];

    container.innerHTML = records.length
      ? records
          .map((row) => {
            return `
              <article class="record-card">
                <div class="record-date">
                  ${escapeHtml(formatDateJa(row.visit_date))}
                </div>

                <div class="record-grid">
                  <div>
                    <small>混雑</small>
                    <strong>
                      ${escapeHtml(row.crowd_label || "—")}
                    </strong>
                  </div>

                  <div>
                    <small>天気</small>
                    <strong>
                      ${escapeHtml(row.weather || "—")}
                    </strong>
                  </div>

                  <div>
                    <small>気温</small>
                    <strong>
                      ${escapeHtml(row.temperature_high ?? "—")}℃
                      /
                      ${escapeHtml(row.temperature_low ?? "—")}℃
                    </strong>
                  </div>

                  <div>
                    <small>価格</small>
                    <strong>
                      ${
                        row.ticket_price
                          ? `${Number(
                              row.ticket_price
                            ).toLocaleString()}円`
                          : "—"
                      }
                    </strong>
                  </div>

                  <div>
                    <small>開園</small>
                    <strong>
                      ${escapeHtml(
                        row.official_open_time || "—"
                      )}
                    </strong>
                  </div>

                  <div>
                    <small>データ元</small>
                    <strong>
                      ${escapeHtml(row.source_type || "—")}
                    </strong>
                  </div>
                </div>

                <div class="dpa-lines">
                  <div class="dpa-line">
                    <span>美女と野獣</span>
                    <strong>
                      ${escapeHtml(
                        formatSellout(
                          row.beauty_sellout_time,
                          row.beauty_is_limit
                        )
                      )}
                    </strong>
                  </div>

                  <div class="dpa-line">
                    <span>ベイマックス</span>
                    <strong>
                      ${escapeHtml(
                        formatSellout(
                          row.baymax_sellout_time,
                          row.baymax_is_limit
                        )
                      )}
                    </strong>
                  </div>

                  <div class="dpa-line">
                    <span>スプラッシュ</span>
                    <strong>
                      ${escapeHtml(
                        formatSellout(
                          row.splash_sellout_time,
                          row.splash_is_limit
                        )
                      )}
                    </strong>
                  </div>
                </div>
              </article>
            `;
          })
          .join("")
      : `
        <div class="empty-card">
          該当するデータはありません。
        </div>
      `;
  } catch (error) {
    state.databaseLoaded = false;

    console.error(
      "データベースの取得に失敗しました。",
      error
    );

    container.innerHTML = `
      <div class="empty-card error-text">
        ${escapeHtml(error.message)}
      </div>
    `;
  }
}

$("forecastButton").addEventListener(
  "click",
  loadForecast
);

$("dbSearchButton").addEventListener(
  "click",
  () => loadDatabase(1)
);

$("prevPageButton").addEventListener(
  "click",
  () => {
    if (state.currentPage > 1) {
      loadDatabase(state.currentPage - 1);
    }
  }
);

$("nextPageButton").addEventListener(
  "click",
  () => {
    loadDatabase(state.currentPage + 1);
  }
);

setupNavigation();
loadStatus();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", async () => {
    try {
      await navigator.serviceWorker.register(
        "/static/service-worker.js"
      );
    } catch (error) {
      console.error(
        "Service Workerの登録に失敗しました。",
        error
      );
    }
  });
}