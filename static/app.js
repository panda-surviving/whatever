const $ = id => document.getElementById(id);

function siteConfirm(message, title = "Are you sure?") {
  return new Promise(resolve => {
    $("confirmModalTitle").textContent = title;
    $("confirmModalMessage").textContent = message;
    $("confirmModalNo").classList.remove("hidden");
    $("confirmModalYes").textContent = "Yes";
    $("confirmModal").classList.remove("hidden");

    const cleanup = (result) => {
      $("confirmModal").classList.add("hidden");
      yesBtn.removeEventListener("click", onYes);
      noBtn.removeEventListener("click", onNo);
      resolve(result);
    };
    const yesBtn = $("confirmModalYes");
    const noBtn = $("confirmModalNo");
    const onYes = () => cleanup(true);
    const onNo = () => cleanup(false);
    yesBtn.addEventListener("click", onYes);
    noBtn.addEventListener("click", onNo);
  });
}

function siteAlert(message, title = "Notice") {
  return new Promise(resolve => {
    $("confirmModalTitle").textContent = title;
    $("confirmModalMessage").textContent = message;
    $("confirmModalNo").classList.add("hidden");
    $("confirmModalYes").textContent = "OK";
    $("confirmModal").classList.remove("hidden");

    const yesBtn = $("confirmModalYes");
    const onYes = () => {
      $("confirmModal").classList.add("hidden");
      yesBtn.removeEventListener("click", onYes);
      resolve(true);
    };
    yesBtn.addEventListener("click", onYes);
  });
}

const money = n =>
  "PKR " + Math.round(Number(n || 0)).toLocaleString();

const esc = s =>
  String(s ?? "").replace(
    /[&<>"']/g,
    c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[c])
  );

let allSymbols = [];
let filteredSymbols = [];
let symbolPage = 1;
const SYMBOLS_PER_PAGE = 50;

async function getJSON(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }

  return data;
}

const pageMeta = {
  dashboard: ["Dashboard", "Your Pakistan equity portfolio"],
  portfolio: ["Portfolio", "Day-by-day P/L and holdings"],
  watchlist: ["Watchlist", "Stocks you're monitoring"],
  transactions: ["Transactions", "Your investment activity"],
  market: ["Markets", "Pakistan market pulse"],
  sentiment: ["Fear & Greed", "Market sentiment"],
  stocks: ["All PSX Stocks", "Full PSX stock directory"],
  stockdetail: ["Stock Profile", "Detailed stock data inside Yalvon360"],
  sectors: ["Sector Rotation", "Sector performance overview"],
  macro: ["Pakistan Macro", "Key economic indicators"],
  news: ["Announcements", "Company and exchange updates"],
  journal: ["Journal", "Analysis, education and podcasts"],
  tools: ["Tools", "Calculators built around your money"],
  worldclock: ["World Clock", "Global trading sessions at a glance"],
  mutualfunds: ["Mutual Funds", "Pakistan mutual fund NAVs"],
  crypto: ["Cryptocurrencies", "Live prices, top coins by market cap"],
  forex: ["Forex", "Live currency exchange rates"],
  commodities: ["Commodities", "Metals, energy and agriculture"],
  screener: ["Screener", "Build filters, one at a time"],
  psxdivergence: ["Divergence Screener", "52-week low & RSI divergence, every PSX stock"],
  forextech: ["Forex Technicals", "RSI divergence & trend structure, major pairs + metals"],
  cryptotech: ["Crypto Technicals", "RSI divergence & trend structure, top cryptocurrencies"],
};

function setupNavigation() {
  document.querySelectorAll(".nav").forEach(btn => {
    btn.addEventListener("click", () => {
      go(btn.dataset.page);
      closeMobileNav();
    });
  });

  document.querySelectorAll("[data-page-link]").forEach(btn => {
    btn.addEventListener("click", () => {
      go(btn.dataset.pageLink);
      closeMobileNav();
    });
  });

  $("globalStatus")?.addEventListener("click", () => go("stocks"));
}

function setupHeaderSearch() {
  const btn = $("headerSearchBtn");
  const bar = $("headerSearchBar");
  const input = $("headerSearchInput");
  const results = $("headerSearchResults");
  if (!btn || !bar) return;

  btn.addEventListener("click", () => {
    bar.classList.toggle("hidden");
    if (!bar.classList.contains("hidden")) input.focus();
  });

  input.addEventListener("input", () => {
    const q = input.value.trim().toUpperCase();
    if (!q) { results.innerHTML = ""; return; }

    const matches = allSymbols
      .filter(s => s.symbol.toUpperCase().includes(q) || s.company.toUpperCase().includes(q))
      .slice(0, 10);

    results.innerHTML = matches.map(s => {
      const live = liveQuoteMap[s.symbol];
      const price = live?.price;
      return `
        <div class="header-search-result" data-symbol="${esc(s.symbol)}">
          <div><b>${esc(s.symbol)}</b><small>${esc(s.company)}</small></div>
          <span>${price != null ? Number(price).toFixed(2) : "—"}</span>
        </div>
      `;
    }).join("") || `<div class="header-search-result muted-note">No matches.</div>`;

    results.querySelectorAll("[data-symbol]").forEach(row => {
      row.addEventListener("click", () => {
        bar.classList.add("hidden");
        input.value = "";
        results.innerHTML = "";
        go("stocks");
        setTimeout(() => openStock(row.dataset.symbol), 150);
      });
    });
  });
}

function closeMobileNav() {
  $("topNavLinks")?.classList.remove("open");
}

function setupMobileNav() {
  const toggle = $("navToggle");
  const links = $("topNavLinks");
  if (!toggle || !links) return;

  toggle.addEventListener("click", () => links.classList.toggle("open"));
}

async function go(page) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  $(page).classList.add("active");

  document.querySelectorAll(".nav").forEach(n => {
    n.classList.toggle("active", n.dataset.page === page);
  });

  $("pageTitle").textContent = pageMeta[page][0];
  $("pageSubtitle").textContent = pageMeta[page][1];

  if (page === "dashboard" || page === "portfolio") await loadPortfolio();
  if (page === "watchlist" || page === "dashboard") await loadWatchlist();
  if (page === "transactions") await loadTransactions();
  if (page === "market" || page === "dashboard") { await loadMarket(); }
  if (page === "dashboard" || page === "market") { await loadMarket360(); }
  if (page === "dashboard") { await loadDashboardHighlights(); }
  if (page === "stocks") { await loadSymbols(); loadLiveQuotes(); }
  if (page === "journal") await loadJournal();
  if (page === "tools") await loadTools();
  if (page === "worldclock") await loadWorldClock();
  if (page === "mutualfunds") await loadMutualFunds();
  if (page === "crypto") await loadCrypto();
  if (page === "forex") await loadForex();
  if (page === "commodities") await loadCommodities();
  if (page === "screener") await loadScreener();
  if (page === "psxdivergence") await loadPsxDivergenceCached();
  if (page === "forextech") await loadForexTechCached();
  if (page === "cryptotech") await loadCryptoTechCached();
  if (["dashboard", "sentiment", "sectors", "macro", "news"].includes(page)) await loadExtras();
  if (page === "macro") await loadMacroPage();
}

function makeSvgLine(values, lineClass = "chart-line") {
  if (!values.length) {
    return `<div class="empty-chart">No recorded data yet</div>`;
  }

  if (values.length === 1) {
    values = [values[0], values[0]];
  }

  const width = 900;
  const height = 260;
  const pad = 14;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(1, max - min);

  const points = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (width - pad * 2);
    const y = height - pad - ((v - min) / spread) * (height - pad * 2);
    return [x, y];
  });

  const path = points
    .map((p, i) => `${i ? "L" : "M"} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`)
    .join(" ");

  const area =
    `${path} L ${points.at(-1)[0]} ${height} L ${points[0][0]} ${height} Z`;

  return `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="rainbowArea" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#7c5cff" stop-opacity=".22"/>
          <stop offset="35%" stop-color="#ef5da8" stop-opacity=".13"/>
          <stop offset="68%" stop-color="#ff9f43" stop-opacity=".10"/>
          <stop offset="100%" stop-color="#22c55e" stop-opacity="0"/>
        </linearGradient>
        <linearGradient id="rainbowStroke" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#7c5cff"/>
          <stop offset="35%" stop-color="#ec4899"/>
          <stop offset="68%" stop-color="#f59e0b"/>
          <stop offset="100%" stop-color="#22c55e"/>
        </linearGradient>
      </defs>

      <g class="chart-grid">
        <line x1="0" y1="65" x2="${width}" y2="65"/>
        <line x1="0" y1="130" x2="${width}" y2="130"/>
        <line x1="0" y1="195" x2="${width}" y2="195"/>
      </g>

      <path class="chart-area" d="${area}"/>
      <path class="${lineClass}" d="${path}"/>
    </svg>
  `;
}

// A small deterministic (seeded, not random-each-render) decorative
// trend shape for cards backed by point-in-time development data that
// has no real recorded history yet (index/commodity/world-market
// cards, all already labeled DEV via their badge). Ends in the
// direction change_pct indicates, so it reads consistently with the
// number next to it — it is NOT a real historical series and is only
// ever used on cards already marked as development data.
function seededSparkline(seed, changePct, points = 10) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const rand = () => { h = (h * 1103515245 + 12345) >>> 0; return (h >>> 8) / 0xFFFFFF; };

  const direction = (changePct || 0) >= 0 ? 1 : -1;
  const values = [50];
  for (let i = 1; i < points; i++) {
    const drift = direction * (i / points) * 12;
    const noise = (rand() - 0.5) * 8;
    values.push(50 + drift + noise);
  }
  values[points - 1] = 50 + direction * 14; // end clearly in the stated direction

  return makeSvgLine(values, direction >= 0 ? "spark-line positive-line" : "spark-line negative-line");
}

function renderStaticCharts() {
  $("heroSparkline").innerHTML = makeSvgLine(
    [100, 101, 100.3, 102.3, 101.8, 103.4, 104.8, 104.1, 105.5, 106.4],
    "spark-line"
  );

  $("indexChart").innerHTML = makeSvgLine(
    [100, 99.7, 100.2, 100.0, 99.8, 100.5, 100.2, 99.9, 99.81],
    "spark-line"
  );
}

let currentPlMode = "cumulative";

function renderInteractiveDualChart(containerId, history, mode = "cumulative") {
  const container = $(containerId);
  if (!container) return;

  if (!history.length) {
    container.innerHTML = `<div class="empty-chart">No recorded data yet</div>`;
    return;
  }

  const width = 900, height = 260, pad = 14;
  const primaryValues = mode === "daily"
    ? history.map(h => Number(h.daily_pnl_change))
    : history.map(h => Number(h.value));
  const secondaryValues = mode === "daily"
    ? history.map(h => Number(h.pnl))
    : history.map(h => Number(h.invested));

  const all = primaryValues.concat(secondaryValues);
  const min = Math.min(...all, 0), max = Math.max(...all, 0);
  const spread = Math.max(1, max - min);
  const n = history.length;

  const xAt = i => pad + (n === 1 ? 0 : (i / (n - 1)) * (width - pad * 2));
  const yAt = v => height - pad - ((v - min) / spread) * (height - pad * 2);

  const pathFor = arr => arr.map((v, i) => `${i ? "L" : "M"} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(" ");
  const primaryPath = pathFor(primaryValues);
  const secondaryPath = pathFor(secondaryValues);
  const primaryArea = `${primaryPath} L ${xAt(n-1).toFixed(1)} ${height} L ${xAt(0).toFixed(1)} ${height} Z`;

  const legendA = mode === "daily" ? "Daily P/L" : "Portfolio Value";
  const legendB = mode === "daily" ? "Cumulative P/L" : "Amount Invested";

  container.innerHTML = `
    <div class="dual-chart-wrap">
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" class="dual-chart-svg">
        <g class="chart-grid">
          <line x1="0" y1="65" x2="${width}" y2="65"/>
          <line x1="0" y1="130" x2="${width}" y2="130"/>
          <line x1="0" y1="195" x2="${width}" y2="195"/>
        </g>
        <path class="chart-area" d="${primaryArea}"/>
        <path class="chart-line dual-line-invested" d="${secondaryPath}"/>
        <path class="chart-line dual-line-value" d="${primaryPath}"/>
        ${history.map((h, i) => `<circle class="dual-hover-dot" data-idx="${i}" cx="${xAt(i).toFixed(1)}" cy="${yAt(primaryValues[i]).toFixed(1)}" r="10" opacity="0"/>`).join("")}
      </svg>
      <div class="dual-chart-tooltip hidden" id="${containerId}Tooltip"></div>
    </div>
    <div class="dual-chart-legend">
      <span><i class="legend-dot legend-dot-value"></i> ${legendA}</span>
      <span><i class="legend-dot legend-dot-invested"></i> ${legendB}</span>
    </div>
  `;

  const tooltip = $(containerId + "Tooltip");
  container.querySelectorAll(".dual-hover-dot").forEach(dot => {
    const i = Number(dot.dataset.idx);
    const h = history[i];
    dot.addEventListener("mouseenter", (e) => {
      const day = new Date(h.day + "T00:00:00");
      tooltip.innerHTML = `
        <b>${day.toLocaleDateString(undefined, {month:"short", day:"numeric", year:"numeric"})}</b>
        <div>Value: <b>${money(h.value)}</b></div>
        <div>Invested: <b>${money(h.invested)}</b></div>
        <div>Daily: <b class="${h.daily_pnl_change >= 0 ? "positive" : "negative"}">${h.daily_pnl_change >= 0 ? "+" : "-"}${money(Math.abs(h.daily_pnl_change))}</b></div>
        <div>Total P/L: <b class="${h.pnl >= 0 ? "positive" : "negative"}">${h.pnl >= 0 ? "+" : "-"}${money(Math.abs(h.pnl))} (${h.pnl_pct.toFixed(2)}%)</b></div>
      `;
      tooltip.classList.remove("hidden");
      const rect = container.getBoundingClientRect();
      const px = (Number(dot.getAttribute("cx")) / width) * rect.width;
      tooltip.style.left = Math.min(rect.width - 160, Math.max(0, px - 70)) + "px";
    });
    dot.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
  });
}


function periodButtonsHtml(activePeriod, target) {
  const periods = ["1D", "1W", "2W", "3W", "1M", "3M", "6M", "1Y"];
  return periods.map(p => `
    <button class="period-btn ${p === activePeriod ? "active" : ""}" data-period="${p}" data-target="${target}">${p}</button>
  `).join("");
}

let currentPortfolioPeriod = "3M";

let lastPortfolioHistory = [];

async function loadPortfolioHistory(period = currentPortfolioPeriod) {
  currentPortfolioPeriod = period;
  const d = await getJSON(`/api/portfolio/history?period=${period}`);
  lastPortfolioHistory = d.history;
  renderPortfolioHistory(d.history);

  ["portfolioPeriodBtns", "dashPeriodBtns"].forEach(id => {
    if ($(id)) $(id).innerHTML = periodButtonsHtml(period, id);
  });
  document.querySelectorAll(".period-btn").forEach(btn => {
    btn.addEventListener("click", () => loadPortfolioHistory(btn.dataset.period));
  });
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".pl-mode-btn");
  if (!btn) return;
  currentPlMode = btn.dataset.plMode;
  document.querySelectorAll(".pl-mode-btn").forEach(b => b.classList.toggle("active", b === btn));
  renderInteractiveDualChart("portfolioPnlChart", lastPortfolioHistory, currentPlMode);
});

function renderPortfolioHistory(history) {
  $("recordedDays").textContent = history.length;

  renderInteractiveDualChart("portfolioPnlChart", history, currentPlMode);
  renderInteractiveDualChart("dashboardPnlChart", history, "cumulative");

  if (!history.length) {
    $("portfolioCalendar").innerHTML =
      `<div class="calendar-empty">No daily snapshots recorded yet.</div>`;
    return;
  }

  $("portfolioCalendar").innerHTML = history.map(item => {
    const daily = Number(item.daily_pnl_change);
    const total = Number(item.pnl);
    const day = new Date(item.day + "T00:00:00");

    return `
      <div class="calendar-day ${daily >= 0 ? "calendar-up" : "calendar-down"}">
        <div class="calendar-date">
          <span>${day.toLocaleDateString(undefined, {month:"short"})}</span>
          <strong>${day.getDate()}</strong>
        </div>

        <div class="calendar-daily">
          <small>DAY</small>
          <b>${daily >= 0 ? "+" : "-"}${money(Math.abs(daily))}</b>
        </div>

        <div class="calendar-total">
          <small>TOTAL P/L</small>
          <span class="${total >= 0 ? "positive" : "negative"}">
            (${total >= 0 ? "+" : "-"}${money(Math.abs(total))})
          </span>
        </div>
      </div>
    `;
  }).join("");
}

async function removeHolding(symbol) {
  const confirmed = await siteConfirm(
    `Remove ${symbol} from your portfolio? This deletes the holding, its transaction history, and its recorded daily calendar. This can't be undone.`,
    `Remove ${symbol}?`
  );
  if (!confirmed) return;

  try {
    const response = await fetch(`/api/portfolio/holding/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Could not remove holding.");
    }

    await loadPortfolio();
  } catch (error) {
    await siteAlert(error.message, "Could not remove holding");
  }
}

let currentHoldings = [];

function sortHoldings(holdings) {
  const mode = $("portfolioSort")?.value || "manual";
  const sorted = holdings.slice();

  if (mode === "pl_desc") sorted.sort((a, b) => b.pl - a.pl);
  if (mode === "pl_asc") sorted.sort((a, b) => a.pl - b.pl);
  if (mode === "pct_desc") sorted.sort((a, b) => b.pl_pct - a.pl_pct);
  if (mode === "value_desc") sorted.sort((a, b) => b.value - a.value);

  return sorted;
}

function renderPortfolioTable() {
  const holdings = sortHoldings(currentHoldings);
  const isManual = ($("portfolioSort")?.value || "manual") === "manual";

  $("portfolioTable").innerHTML = holdings.map(h => `
    <tr class="clickable-row ${isManual ? "draggable-row" : ""} ${h.pl >= 0 ? "tint-positive" : "tint-negative"}"
        data-holding-symbol="${esc(h.symbol)}" draggable="${isManual}" data-drag-symbol="${esc(h.symbol)}">
      <td class="drag-handle">${isManual ? "⠿" : ""}</td>
      <td class="symbol">${esc(h.symbol)}</td>
      <td>${esc(h.company)}</td>
      <td>${esc(h.sector)}</td>
      <td>${Number(h.price).toFixed(2)}</td>
      <td class="holding-sparkline">${h.recent_trend && h.recent_trend.length > 1 ? makeSvgLine(h.recent_trend, h.pl >= 0 ? "chart-line positive-line" : "chart-line negative-line") : "<span class=\"soft-chip\">Building…</span>"}</td>
      <td>${Number(h.quantity).toLocaleString()}</td>
      <td>${Number(h.avg_cost).toFixed(2)}</td>
      <td>${money(h.invested)}</td>
      <td>${money(h.value)}</td>
      <td class="${h.pl >= 0 ? "positive" : "negative"}">
        ${h.pl >= 0 ? "+" : "-"}${money(Math.abs(h.pl))}
      </td>
      <td class="${h.pl_pct >= 0 ? "positive" : "negative"}">
        ${h.pl_pct >= 0 ? "+" : ""}${h.pl_pct.toFixed(2)}%
      </td>
      <td>${esc(h.acquired_date || "—")}</td>
      <td>
        <button class="icon-only-btn" data-holding-symbol="${esc(h.symbol)}" title="View calendar">📅</button>
      </td>
      <td>
        <button class="remove-holding-btn" data-remove-symbol="${esc(h.symbol)}" title="Remove ${esc(h.symbol)} from portfolio">
          ×
        </button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="14"><div class="empty-chart">No holdings yet. Add a transaction to get started.</div></td></tr>`;

  document.querySelectorAll("[data-holding-symbol]").forEach(el => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      openHoldingCalendar(el.dataset.holdingSymbol);
    });
  });

  document.querySelectorAll("[data-remove-symbol]").forEach(el => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      removeHolding(el.dataset.removeSymbol);
    });
  });

  if (isManual) setupPortfolioDragReorder();
}

function setupPortfolioDragReorder() {
  const tbody = $("portfolioTable");
  let dragSymbol = null;

  tbody.querySelectorAll("[data-drag-symbol]").forEach(row => {
    row.addEventListener("dragstart", (e) => {
      dragSymbol = row.dataset.dragSymbol;
      row.classList.add("dragging");
    });
    row.addEventListener("dragend", () => row.classList.remove("dragging"));
    row.addEventListener("dragover", (e) => e.preventDefault());
    row.addEventListener("drop", async (e) => {
      e.preventDefault();
      const targetSymbol = row.dataset.dragSymbol;
      if (!dragSymbol || dragSymbol === targetSymbol) return;

      const order = currentHoldings.map(h => h.symbol);
      const from = order.indexOf(dragSymbol);
      const to = order.indexOf(targetSymbol);
      order.splice(from, 1);
      order.splice(to, 0, dragSymbol);

      currentHoldings.sort((a, b) => order.indexOf(a.symbol) - order.indexOf(b.symbol));
      renderPortfolioTable();

      await getJSON("/api/portfolio/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: order }),
      });
    });
  });
}

$("portfolioSort")?.addEventListener("change", renderPortfolioTable);

async function loadPortfolio() {
  const d = await getJSON("/api/portfolio");

  $("value").textContent = money(d.value);
  $("invested").textContent = money(d.invested);
  $("pl").textContent = `${d.pl >= 0 ? "+" : "-"}${money(Math.abs(d.pl))}`;
  $("pl").className = d.pl >= 0 ? "positive" : "negative";
  $("plPct").textContent = `${d.pl_pct >= 0 ? "+" : ""}${d.pl_pct.toFixed(2)}% return`;

  $("portfolioValue").textContent = money(d.value);
  $("portfolioInvested").textContent = money(d.invested);
  $("portfolioPnl").textContent = `${d.pl >= 0 ? "+" : "-"}${money(Math.abs(d.pl))}`;
  $("portfolioPnl").className = d.pl >= 0 ? "positive" : "negative";
  $("portfolioPnlPct").textContent = `${d.pl_pct >= 0 ? "+" : ""}${d.pl_pct.toFixed(2)}%`;

  currentHoldings = d.holdings;
  renderPortfolioTable();

  $("topHoldings").innerHTML = d.holdings
    .slice()
    .sort((a, b) => b.value - a.value)
    .slice(0, 5)
    .map(h => `
      <tr class="clickable-row" data-holding-symbol="${esc(h.symbol)}">
        <td class="symbol">${esc(h.symbol)}</td>
        <td>${Number(h.price).toFixed(2)}</td>
        <td>${Number(h.quantity).toLocaleString()}</td>
        <td>${money(h.value)}</td>
        <td class="${h.pl >= 0 ? "positive" : "negative"}">
          ${h.pl >= 0 ? "+" : "-"}${money(Math.abs(h.pl))}
        </td>
      </tr>
    `).join("");

  document.querySelectorAll("#topHoldings [data-holding-symbol]").forEach(el => {
    el.addEventListener("click", () => openHoldingCalendar(el.dataset.holdingSymbol));
  });

  const total = d.value || 1;
  $("allocation").innerHTML = d.holdings.map(h => {
    const pct = (h.value / total) * 100;

    return `
      <div class="allocation-row">
        <span>
          <b>${esc(h.symbol)}</b>
          <small>${esc(h.sector)}</small>
        </span>
        <strong>${pct.toFixed(1)}%</strong>
      </div>
      <div class="allocation-bar">
        <i style="width:${Math.min(100, pct)}%"></i>
      </div>
    `;
  }).join("");

  loadPortfolioHistory(currentPortfolioPeriod);
}

async function recordToday() {
  const btn = $("recordTodayBtn");
  const old = btn.textContent;

  try {
    btn.disabled = true;
    btn.textContent = "Recording…";
    await getJSON("/api/portfolio/snapshot", {method:"POST"});
    await loadPortfolio();
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

let currentWatchlist = [];

const ASSET_TYPE_LABELS = { stock: "Stock", crypto: "Crypto", forex: "Forex", fund: "Fund" };

async function loadWatchlist() {
  currentWatchlist = await getJSON("/api/watchlist");
  renderWatchlist();
}

function sortWatchlist(items) {
  const mode = $("watchSort")?.value || "manual";
  const sorted = items.slice();

  if (mode === "change_desc") sorted.sort((a, b) => (b.change_pct ?? -Infinity) - (a.change_pct ?? -Infinity));
  if (mode === "change_asc") sorted.sort((a, b) => (a.change_pct ?? Infinity) - (b.change_pct ?? Infinity));
  if (mode === "price_desc") sorted.sort((a, b) => (b.price ?? -Infinity) - (a.price ?? -Infinity));
  if (mode === "name_asc") sorted.sort((a, b) => (a.name || a.symbol).localeCompare(b.name || b.symbol));

  return sorted;
}

function renderWatchlist() {
  const items = sortWatchlist(currentWatchlist);
  const isManual = ($("watchSort")?.value || "manual") === "manual";

  $("watchCount").textContent = `${items.length} item${items.length === 1 ? "" : "s"}`;

  $("watchTable").innerHTML = items.map(x => {
    const pct = x.change_pct;
    return `
      <tr class="${isManual ? "draggable-row" : ""} ${pct == null ? "" : (pct >= 0 ? "tint-positive" : "tint-negative")}"
          draggable="${isManual}" data-drag-symbol="${esc(x.symbol)}">
        <td class="drag-handle">${isManual ? "⠿" : ""}</td>
        <td><span class="soft-chip">${esc(ASSET_TYPE_LABELS[x.asset_type] || "Stock")}</span></td>
        <td class="symbol">${esc(x.symbol)}</td>
        <td>${esc(x.name || "—")}</td>
        <td>${x.price == null ? "—" : Number(x.price).toLocaleString(undefined, {maximumFractionDigits: x.price < 1 ? 6 : 2})}</td>
        <td class="${pct == null ? "" : (pct >= 0 ? "positive" : "negative")}">
          ${pct == null ? "—" : `${pct >= 0 ? "+" : ""}${Number(pct).toFixed(2)}%`}
        </td>
        <td><button class="remove-holding-btn" data-watch-remove="${esc(x.symbol)}" title="Remove from watchlist">×</button></td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="7"><div class="empty-chart">Your watchlist is empty. Add a symbol above, or use the ★ icon on any stock/crypto/forex/fund row.</div></td></tr>`;

  document.querySelectorAll("[data-watch-remove]").forEach(btn => {
    btn.addEventListener("click", async () => {
      await getJSON(`/api/watchlist/${encodeURIComponent(btn.dataset.watchRemove)}`, { method: "DELETE" });
      await loadWatchlist();
    });
  });

  if (isManual) setupWatchlistDragReorder();

  if ($("dashWatchlistBox")) {
    $("dashWatchlistBox").innerHTML = items.length
      ? items.map(x => {
          const pct = x.change_pct;
          return `
            <div class="dash-watchlist-row ${pct == null ? "" : (pct >= 0 ? "tint-positive" : "tint-negative")}">
              <span class="soft-chip">${esc(ASSET_TYPE_LABELS[x.asset_type] || "Stock")}</span>
              <div class="dash-watchlist-info">
                <b>${esc(x.symbol)}</b>
                <small>${esc(x.name || "—")}</small>
              </div>
              <div class="dash-watchlist-price">
                <span>${x.price == null ? "—" : Number(x.price).toLocaleString(undefined, {maximumFractionDigits: x.price < 1 ? 6 : 2})}</span>
                <small class="${pct == null ? "" : (pct >= 0 ? "positive" : "negative")}">${pct == null ? "" : `${pct >= 0 ? "+" : ""}${Number(pct).toFixed(2)}%`}</small>
              </div>
            </div>
          `;
        }).join("")
      : `<div class="empty-chart">Your watchlist is empty. Add symbols from the Watchlist page or the ★ icon anywhere.</div>`;
  }
}

function setupWatchlistDragReorder() {
  const tbody = $("watchTable");
  let dragSymbol = null;

  tbody.querySelectorAll("[data-drag-symbol]").forEach(row => {
    row.addEventListener("dragstart", () => { dragSymbol = row.dataset.dragSymbol; row.classList.add("dragging"); });
    row.addEventListener("dragend", () => row.classList.remove("dragging"));
    row.addEventListener("dragover", (e) => e.preventDefault());
    row.addEventListener("drop", async (e) => {
      e.preventDefault();
      const targetSymbol = row.dataset.dragSymbol;
      if (!dragSymbol || dragSymbol === targetSymbol) return;

      const order = currentWatchlist.map(x => x.symbol);
      const from = order.indexOf(dragSymbol);
      const to = order.indexOf(targetSymbol);
      order.splice(from, 1);
      order.splice(to, 0, dragSymbol);

      currentWatchlist.sort((a, b) => order.indexOf(a.symbol) - order.indexOf(b.symbol));
      renderWatchlist();

      await getJSON("/api/watchlist/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: order }),
      });
    });
  });
}

$("watchSort")?.addEventListener("change", renderWatchlist);

let universalSearchFilter = "all";
let universalSearchDebounce = null;

$("watchUniversalSearch")?.addEventListener("input", () => {
  clearTimeout(universalSearchDebounce);
  const q = $("watchUniversalSearch").value.trim();
  if (!q) { $("watchUniversalResults").innerHTML = ""; return; }
  universalSearchDebounce = setTimeout(() => runUniversalSearch(q), 220);
});

document.querySelectorAll(".usf-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".usf-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    universalSearchFilter = btn.dataset.usf;
    const q = $("watchUniversalSearch").value.trim();
    if (q) runUniversalSearch(q);
  });
});

async function runUniversalSearch(q) {
  $("watchUniversalResults").innerHTML = `<div class="loading-panel">Searching…</div>`;
  try {
    const d = await getJSON(`/api/search-all?q=${encodeURIComponent(q)}`);
    const results = universalSearchFilter === "all"
      ? d.results
      : d.results.filter(r => r.asset_type === universalSearchFilter);

    $("watchUniversalResults").innerHTML = results.length
      ? results.map(r => `
          <div class="universal-search-row">
            <span class="soft-chip">${esc(ASSET_TYPE_LABELS[r.asset_type] || r.asset_type)}</span>
            <div class="universal-search-info">
              <b>${esc(r.symbol)}</b>
              <small>${esc(r.name)}</small>
            </div>
            <div class="universal-search-price">
              ${r.price != null ? Number(r.price).toLocaleString(undefined, {maximumFractionDigits: r.price < 1 ? 6 : 2}) : "—"}
              ${r.change_pct != null ? `<small class="${r.change_pct >= 0 ? "positive" : "negative"}">${r.change_pct >= 0 ? "+" : ""}${Number(r.change_pct).toFixed(2)}%</small>` : ""}
            </div>
            <button class="secondary universal-search-add-btn" data-add-symbol="${esc(r.symbol)}" data-add-type="${esc(r.asset_type)}" data-add-name="${esc(r.name)}" data-add-price="${r.price ?? ""}" data-add-pct="${r.change_pct ?? ""}">+ Add</button>
          </div>
        `).join("")
      : `<div class="empty-chart">No matches for "${esc(q)}".</div>`;

    document.querySelectorAll(".universal-search-add-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const ok = await addToWatchlist(
          btn.dataset.addSymbol, btn.dataset.addType, btn.dataset.addName,
          btn.dataset.addPrice ? Number(btn.dataset.addPrice) : null,
          btn.dataset.addPct ? Number(btn.dataset.addPct) : null
        );
        if (ok) {
          btn.textContent = "✓ Added";
          btn.disabled = true;
          await loadWatchlist();
        }
      });
    });
  } catch (error) {
    $("watchUniversalResults").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}

async function addToWatchlist(symbol, assetType = "stock", displayName = null, price = null, changePct = null) {
  try {
    await getJSON("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol, asset_type: assetType, display_name: displayName,
        price, change_pct: changePct,
      }),
    });
    return true;
  } catch (error) {
    await siteAlert(error.message);
    return false;
  }
}

$("dashQuickAddBtn")?.addEventListener("click", async () => {
  const symbol = $("dashQuickAddSymbol").value.trim().toUpperCase();
  if (!symbol) return;
  const ok = await addToWatchlist(symbol, "stock");
  $("dashQuickAddResult").textContent = ok ? `${symbol} added to your watchlist.` : "Could not add symbol.";
  $("dashQuickAddSymbol").value = "";
});

function moverRow(stock, mode = "change") {
  const change = Number(stock.change_pct || 0);

  return `
    <div class="mover-row">
      <div>
        <strong>${esc(stock.symbol)}</strong>
        <small>${esc(stock.company)}</small>
      </div>
      <div class="mover-right">
        <b>${stock.price == null ? "—" : Number(stock.price).toFixed(2)}</b>
        ${
          mode === "volume"
            ? `<small>Vol ${stock.volume == null ? "—" : Number(stock.volume).toLocaleString()}</small>`
            : `<small class="${change >= 0 ? "positive" : "negative"}">
                ${change >= 0 ? "▲" : "▼"} ${Math.abs(change).toFixed(2)}%
              </small>`
        }
      </div>
    </div>
  `;
}

async function loadMarket() {
  const d = await getJSON("/api/market");
  const stocks = d.stocks;

  $("dashKse").textContent = Number(d.kse100.price).toLocaleString();
  $("dashKseChange").textContent =
    `${Number(d.kse100.change_pct) >= 0 ? "▲" : "▼"} ${Math.abs(Number(d.kse100.change_pct)).toFixed(2)}%`;
  $("dashAdvancers").textContent = d.advancers;
  $("dashDecliners").textContent = d.decliners;

  const gainers = [...stocks]
    .sort((a,b) => Number(b.change_pct || 0) - Number(a.change_pct || 0))
    .slice(0,5);

  const losers = [...stocks]
    .sort((a,b) => Number(a.change_pct || 0) - Number(b.change_pct || 0))
    .slice(0,5);

  const active = [...stocks]
    .sort((a,b) => Number(b.volume || 0) - Number(a.volume || 0))
    .slice(0,5);

  $("dashTopGainer").textContent = gainers[0]?.symbol || "—";
  $("dashMostActive").textContent = active[0]?.symbol || "—";

  // Render the KSE-100 mini index + advancers/decliners + movers lists
  // for whichever of the two contexts are present on this page: the
  // Markets page (plain ids) and/or the Dashboard's merged "Complete
  // Market Detail" section (ids suffixed "Home").
  const renderMoversFor = (suffix) => {
    if (!$("kse100Price" + suffix)) return;

    $("kse100Price" + suffix).textContent = Number(d.kse100.price).toLocaleString(undefined, {
      minimumFractionDigits:2,
      maximumFractionDigits:2
    });
    $("kse100Change" + suffix).textContent =
      `${Number(d.kse100.change_pct) >= 0 ? "▲" : "▼"} ${Math.abs(Number(d.kse100.change_pct)).toFixed(2)}%`;
    $("marketAdvancers" + suffix).textContent = d.advancers;
    $("marketDecliners" + suffix).textContent = d.decliners;
    $("topGainers" + suffix).innerHTML = gainers.map(x => moverRow(x)).join("");
    $("topLosers" + suffix).innerHTML = losers.map(x => moverRow(x)).join("");
    $("mostActive" + suffix).innerHTML = active.map(x => moverRow(x,"volume")).join("");
  };

  renderMoversFor("");
  renderMoversFor("Home");

  try {
    const directory = await getJSON("/api/symbols");
    if ($("directoryCount")) $("directoryCount").textContent = directory.count;
    if ($("marketDirectoryCount")) $("marketDirectoryCount").textContent = directory.count;
    if ($("marketDirectoryCountHome")) $("marketDirectoryCountHome").textContent = directory.count;
    $("globalStatus").textContent = `${directory.count} PSX symbols`;
  } catch (error) {
    console.error(error);
  }
}

function populateSectorFilter() {
  const sectors = [...new Set(allSymbols.map(x => x.sector).filter(Boolean))].sort();

  $("sectorFilter").innerHTML =
    `<option value="">All sectors</option>` +
    sectors.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
}

function applySymbolFilters() {
  const q = $("allStockSearch").value.trim().toUpperCase();
  const sector = $("sectorFilter").value;
  const move = $("stockMoveFilter")?.value || "";

  filteredSymbols = allSymbols.filter(item => {
    const searchMatch =
      !q ||
      item.symbol.toUpperCase().includes(q) ||
      item.company.toUpperCase().includes(q) ||
      item.sector.toUpperCase().includes(q);

    const sectorMatch = !sector || item.sector === sector;

    const changePct = liveQuoteMap[item.symbol]?.change_pct;
    let moveMatch = true;
    if (move === "up") moveMatch = changePct != null && changePct > 0;
    if (move === "down") moveMatch = changePct != null && changePct < 0;
    if (move === "big_up") moveMatch = changePct != null && changePct >= 5;
    if (move === "big_down") moveMatch = changePct != null && changePct <= -5;

    return searchMatch && sectorMatch && moveMatch;
  });

  symbolPage = 1;
  renderSymbolPage();
}

let liveQuoteMap = {};

function trendBadge(state) {
  if (!state) return `<span class="soft-chip">—</span>`;
  const map = {
    golden_cross: ["Golden Cross", "badge-live"],
    death_cross: ["Death Cross", "badge-dev"],
    bullish_alignment: ["Bullish (50>200)", "badge-live"],
    bearish_alignment: ["Bearish (50<200)", "badge-dev"],
  };
  const [label, cls] = map[state] || [state, ""];
  return `<span class="data-badge ${cls}">${label}</span>`;
}

function watchStarButton(symbol, assetType, name, price, changePct) {
  return `<button class="watch-star-btn" data-watch-add="${esc(symbol)}" data-watch-type="${assetType}"
            data-watch-name="${esc(name || symbol)}" data-watch-price="${price ?? ""}" data-watch-pct="${changePct ?? ""}"
            title="Add to watchlist">☆</button>`;
}

function wireWatchStarButtons(root = document) {
  root.querySelectorAll("[data-watch-add]").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const ok = await addToWatchlist(
        btn.dataset.watchAdd, btn.dataset.watchType, btn.dataset.watchName,
        btn.dataset.watchPrice ? Number(btn.dataset.watchPrice) : null,
        btn.dataset.watchPct ? Number(btn.dataset.watchPct) : null
      );
      if (ok) { btn.textContent = "★"; btn.classList.add("watched"); }
    });
  });
}

function renderSymbolPage() {
  const totalPages = Math.max(1, Math.ceil(filteredSymbols.length / SYMBOLS_PER_PAGE));
  symbolPage = Math.max(1, Math.min(symbolPage, totalPages));

  const start = (symbolPage - 1) * SYMBOLS_PER_PAGE;
  const items = filteredSymbols.slice(start, start + SYMBOLS_PER_PAGE);

  $("allStocksTable").innerHTML = items.map(item => {
    const live = liveQuoteMap[item.symbol];
    const price = live?.price;
    const changePct = live?.change_pct;
    const pe = live?.pe_ratio;
    const rsi = live?.rsi14;
    const trend = live?.golden_death_cross;
    const dataDays = live?.data_days || 0;
    const volume = live?.volume;
    const fundsHolding = live?.funds_holding;

    return `
      <tr class="${changePct == null ? "" : (changePct >= 0 ? "tint-positive" : "tint-negative")}">
        <td>${watchStarButton(item.symbol, "stock", item.company, price, changePct)}</td>
        <td class="symbol">${esc(item.symbol)}</td>
        <td>${esc(item.company)}</td>
        <td><span class="sector-tag">${esc(item.sector || "—")}</span></td>
        <td>${price == null ? "—" : Number(price).toFixed(2)}</td>
        <td class="${changePct == null ? "" : (changePct >= 0 ? "positive" : "negative")}">
          ${changePct == null ? "—" : `${changePct >= 0 ? "+" : ""}${Number(changePct).toFixed(2)}%`}
        </td>
        <td>${volume == null ? "—" : Number(volume).toLocaleString()}</td>
        <td>${pe == null ? "—" : Number(pe).toFixed(2)}</td>
        <td>
          ${rsi == null
            ? `<span class="soft-chip" title="Needs 15 recorded trading days">${dataDays}/15 days</span>`
            : `<span class="${rsi >= 70 ? "negative" : (rsi <= 30 ? "positive" : "")}">${rsi.toFixed(1)}</span>`}
        </td>
        <td>${trendBadge(trend)}</td>
        <td title="${fundsHolding != null ? "" : "Only tracked for a handful of top stocks — see Markets → Top Stocks Three Ways"}">
          ${fundsHolding != null ? `${fundsHolding} funds` : "—"}
        </td>
        <td>
          <button class="view-stock-button" data-symbol="${esc(item.symbol)}">
            View in Yalvon360 →
          </button>
        </td>
      </tr>
    `;
  }).join("");

  document.querySelectorAll(".view-stock-button").forEach(button => {
    button.addEventListener("click", () => openStock(button.dataset.symbol));
  });
  wireWatchStarButtons($("allStocksTable"));

  $("allStockCount").textContent = `${filteredSymbols.length.toLocaleString()} symbols`;
  $("pageInfo").textContent = `Page ${symbolPage} of ${totalPages}`;
  $("prevPageBtn").disabled = symbolPage <= 1;
  $("nextPageBtn").disabled = symbolPage >= totalPages;
}

async function loadLiveQuotes() {
  try {
    const d = await getJSON("/api/stocks/live");
    liveQuoteMap = {};
    d.items.forEach(q => { liveQuoteMap[q.symbol] = q; });

    $("liveQuotesStatus").textContent = d.updated_at
      ? `Live prices: ${d.items.length} symbols, updated ${new Date(d.updated_at).toLocaleTimeString()}`
      : "Live prices: fetching for the first time…";

    if (d.recording_progress) {
      const p = d.recording_progress;
      $("technicalsProgress").innerHTML = p.days_recorded > 0
        ? `📈 Technical-indicator history: <b>${p.days_recorded}</b> trading day${p.days_recorded === 1 ? "" : "s"} recorded since ${esc(p.started_on)}. RSI activates at 15 days, 50/100/200-day averages at 50/100/200 days.`
        : `📈 Technical-indicator recording starts with your first live price refresh — RSI, moving averages, MACD and Golden/Death Cross will activate automatically as history builds up.`;
    }

    applySymbolFilters();
  } catch (error) {
    $("liveQuotesStatus").textContent = "Live prices: unavailable";
  }
}

async function refreshLiveQuotes() {
  const btn = $("refreshLiveBtn");
  const old = btn.textContent;

  try {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    await getJSON("/api/stocks/live/refresh", { method: "POST" });
    $("liveQuotesStatus").textContent = "Live prices: refreshing in the background…";
    setTimeout(loadLiveQuotes, 4000);
  } catch (error) {
    await siteAlert(error.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

$("refreshLiveBtn")?.addEventListener("click", refreshLiveQuotes);

async function loadSymbols(force=false) {
  if (allSymbols.length && !force) return;

  $("allStockCount").textContent = "Loading PSX symbols…";

  const d = await getJSON("/api/symbols");

  allSymbols = d.symbols;
  filteredSymbols = allSymbols.slice();

  $("directoryCount").textContent = d.count;
  $("marketDirectoryCount").textContent = d.count;
  $("globalStatus").textContent = `${d.count} PSX symbols`;

  populateSectorFilter();
  renderSymbolPage();
}

async function refreshSymbols() {
  const btn = $("refreshSymbolsBtn");
  const old = btn.textContent;

  try {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    await getJSON("/api/symbols/refresh", {method:"POST"});
    allSymbols = [];
    await loadSymbols(true);
  } catch (error) {
    await siteAlert(error.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function metric(label, value) {
  return `
    <div class="quote-metric">
      <small>${label}</small>
      <strong>${value == null ? "—" : value}</strong>
    </div>
  `;
}

function renderRange(label, low, current, high) {
  if (low == null || high == null || high <= low) {
    return `
      <div class="range-block">
        <div class="range-label">
          <strong>${label}</strong>
          <span>Not available</span>
        </div>
      </div>
    `;
  }

  const pct = Math.max(0, Math.min(100, ((Number(current) - Number(low)) / (Number(high) - Number(low))) * 100));

  return `
    <div class="range-block">
      <div class="range-label">
        <strong>${label}</strong>
        <span>${Number(low).toFixed(2)} — ${Number(high).toFixed(2)}</span>
      </div>

      <div class="detail-range-track">
        <i style="left:${pct}%"></i>
      </div>
    </div>
  `;
}

async function openStock(symbol) {
  await go("stockdetail");

  $("detailSymbol").textContent = symbol;
  $("detailCompany").textContent = "Loading…";
  $("detailPrice").textContent = "—";
  $("detailChange").textContent = "Loading quote…";
  $("quoteMetrics").innerHTML = `<div class="loading-panel">Loading stock data…</div>`;
  $("stockDetailChart").innerHTML = `<div class="loading-panel">Loading graph…</div>`;

  try {
    const d = await getJSON(`/api/stock/${encodeURIComponent(symbol)}`);

    $("detailSymbol").textContent = d.symbol;
    $("detailCompany").textContent = `${d.company || d.symbol}${d.sector ? " · " + d.sector : ""}`;
    $("detailPrice").textContent = d.price == null ? "—" : `Rs. ${Number(d.price).toFixed(2)}`;

    const change = Number(d.change_pct || 0);
    $("detailChange").textContent =
      d.change_pct == null ? "Change unavailable" : `${change >= 0 ? "▲" : "▼"} ${Math.abs(change).toFixed(2)}%`;
    $("detailChange").className = d.change_pct == null ? "" : (change >= 0 ? "positive" : "negative");

    $("detailSource").textContent = d.source || "PSX";
    $("detailUpdated").textContent = d.last_update || d.fetched_at || "Updated";

    $("quoteMetrics").innerHTML =
      metric("Open", d.open == null ? null : Number(d.open).toFixed(2)) +
      metric("High", d.high == null ? null : Number(d.high).toFixed(2)) +
      metric("Low", d.low == null ? null : Number(d.low).toFixed(2)) +
      metric("Volume", d.volume == null ? null : Number(d.volume).toLocaleString()) +
      metric("LDCP", d.ldcp == null ? null : Number(d.ldcp).toFixed(2)) +
      metric("P/E (TTM)", d.pe_ratio == null ? null : Number(d.pe_ratio).toFixed(2)) +
      metric("Ask", d.ask_price == null ? null : Number(d.ask_price).toFixed(2)) +
      metric("Bid", d.bid_price == null ? null : Number(d.bid_price).toFixed(2)) +
      metric("1Y Change", d.one_year_change == null ? null : `${Number(d.one_year_change).toFixed(2)}%`) +
      metric("YTD Change", d.ytd_change == null ? null : `${Number(d.ytd_change).toFixed(2)}%`);

    const series = Array.isArray(d.series) ? d.series : [];
    const values = series.map(x => Number(x.y)).filter(Number.isFinite);

    $("stockDetailChart").innerHTML =
      values.length
        ? makeSvgLine(values, "detail-line")
        : `<div class="empty-chart">Intraday graph is not available from the current response.</div>`;

    $("stockRanges").innerHTML =
      renderRange("Day Range", d.day_low, d.price, d.day_high) +
      renderRange("52-Week Range", d.low52, d.price, d.high52) +
      renderRange("Circuit Breaker", d.circuit_low, d.price, d.circuit_high);

  } catch (error) {
    $("detailCompany").textContent = "Unable to load stock data";
    $("quoteMetrics").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
    $("stockDetailChart").innerHTML = `<div class="empty-chart">No graph available.</div>`;
  }

  loadFundamentals(symbol);
  loadTechnicalVerdict(symbol);
}

async function loadTechnicalVerdict(symbol) {
  $("technicalVerdictBody").innerHTML = `<div class="loading-panel">Computing verdict…</div>`;
  $("pivotPointsBody").innerHTML = `<div class="loading-panel">Computing levels…</div>`;

  try {
    const d = await getJSON(`/api/stock/${encodeURIComponent(symbol)}/verdict`);

    if (!d.available) {
      const msg = `<div class="empty-chart">${esc(d.note || "Not enough data to compute a verdict yet.")}</div>`;
      $("technicalVerdictBody").innerHTML = msg;
      $("pivotPointsBody").innerHTML = msg;
      return;
    }

    const verdictClass = d.verdict.toLowerCase().replace(/\s+/g, "-");
    $("technicalVerdictBody").innerHTML = `
      <div class="verdict-summary">
        <div class="verdict-score-ring ${verdictClass}">${d.score}</div>
        <div>
          <div class="verdict-label">${esc(d.verdict)}</div>
          <div class="verdict-price-note">Weighted technical score out of 100, at Rs. ${Number(d.price).toFixed(2)}</div>
        </div>
      </div>
      <div class="table-scroll">
        <table class="verdict-breakdown-table">
          <thead><tr><th>Indicator</th><th>Weight</th><th>Signal</th><th>Contribution</th></tr></thead>
          <tbody>
            ${d.breakdown.map(b => `
              <tr>
                <td>${esc(b.indicator)}</td>
                <td>${b.weight}</td>
                <td><span class="lean-tag lean-${b.lean}">${b.used ? b.lean : "n/a"}</span></td>
                <td>${b.contribution == null ? "—" : b.contribution}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    const pp = d.pivot_points;
    const pivotRows = (levels) => `
      <table class="pivot-table">
        <tr class="pivot-row-r"><td>R3</td><td>${levels.r3}</td></tr>
        <tr class="pivot-row-r"><td>R2</td><td>${levels.r2}</td></tr>
        <tr class="pivot-row-r"><td>R1</td><td>${levels.r1}</td></tr>
        <tr class="pivot-row-p"><td>Pivot (P)</td><td>${levels.pivot}</td></tr>
        <tr class="pivot-row-s"><td>S1</td><td>${levels.s1}</td></tr>
        <tr class="pivot-row-s"><td>S2</td><td>${levels.s2}</td></tr>
        <tr class="pivot-row-s"><td>S3</td><td>${levels.s3}</td></tr>
      </table>
    `;

    $("pivotBasisNote").textContent = pp.basis_date
      ? `Classic and Fibonacci pivot points, based on the trading day ending ${pp.basis_date}.`
      : "Classic and Fibonacci pivot points from the most recent completed trading day.";

    $("pivotPointsBody").innerHTML = `
      <div class="pivot-tables-row">
        <div class="pivot-table-block"><h4>Classic Pivot Points</h4>${pivotRows(pp.classic)}</div>
        <div class="pivot-table-block"><h4>Fibonacci Pivot Points</h4>${pivotRows(pp.fibonacci)}</div>
      </div>
    `;
  } catch (error) {
    const msg = `<div class="error-panel">${esc(error.message)}</div>`;
    $("technicalVerdictBody").innerHTML = msg;
    $("pivotPointsBody").innerHTML = msg;
  }
}

async function loadFundamentals(symbol) {
  $("fundamentalsMetrics").innerHTML = `<div class="loading-panel">Loading…</div>`;

  try {
    const f = await getJSON(`/api/stock/${encodeURIComponent(symbol)}/fundamentals`);
    $("fundamentalsNote").textContent = f.note;

    $("fundamentalsMetrics").innerHTML =
      metric("P/E (TTM)", f.pe_ratio_ttm == null ? null : Number(f.pe_ratio_ttm).toFixed(2)) +
      metric("1Y Change", f.one_year_change_pct == null ? null : `${Number(f.one_year_change_pct).toFixed(2)}%`) +
      metric("YTD Change", f.ytd_change_pct == null ? null : `${Number(f.ytd_change_pct).toFixed(2)}%`) +
      metric("LDCP", f.ldcp == null ? null : Number(f.ldcp).toFixed(2)) +
      metric("EPS (TTM)", f.eps_ttm == null ? "Needs data vendor" : f.eps_ttm) +
      metric("Book Value / Share", f.book_value_per_share == null ? "Needs data vendor" : f.book_value_per_share) +
      metric("Dividend Yield", f.dividend_yield_pct == null ? "Needs data vendor" : `${f.dividend_yield_pct}%`) +
      metric("Dividend History", f.dividend_history.length ? `${f.dividend_history.length} records` : "Needs data vendor");

    if (f.pe_ratio_ttm != null) {
      const peScaled = Math.max(0, Math.min(100, (f.pe_ratio_ttm / 40) * 100));
      $("peGaugeRing").style.setProperty("--val", peScaled);
      $("peGaugeValue").textContent = Number(f.pe_ratio_ttm).toFixed(1);
    } else {
      $("peGaugeValue").textContent = "—";
    }

    const [low, high] = f.week52_range;
    if (low != null && high != null && f.price != null && high > low) {
      const pct = ((f.price - low) / (high - low)) * 100;
      $("week52GaugeBar").innerHTML = `
        <div class="range-gauge-track"><i style="left:${Math.max(0,Math.min(100,pct))}%"></i></div>
        <div class="range-gauge-labels"><span>${low}</span><span>${high}</span></div>
      `;
    } else {
      $("week52GaugeBar").innerHTML = `<div class="empty-chart">Range unavailable</div>`;
    }
  } catch (error) {
    $("fundamentalsMetrics").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}

function sectorRowHtml(item, dismissible = false) {
  const change = Number(item.change);
  return `
    <div class="sector-row clickable-row" data-sector-link="${esc(item.sector)}">
      <div>
        <strong>${esc(item.sector)}</strong>
        <small>${change >= 0 ? "Positive momentum" : "Negative momentum"}</small>
      </div>
      <div class="sector-meter">
        <i class="${change >= 0 ? "up" : "down"}"
           style="width:${Math.min(100, Math.abs(change) * 28)}%"></i>
      </div>
      <b class="${change >= 0 ? "positive" : "negative"}">
        ${change >= 0 ? "+" : ""}${change.toFixed(2)}%
      </b>
      ${dismissible ? `<button class="icon-only-btn sector-dismiss-btn" data-sector-dismiss="${esc(item.sector)}" title="Hide from dashboard strip">×</button>` : ""}
    </div>
  `;
}

function getHiddenSectors() {
  try { return JSON.parse(localStorage.getItem("yalvon_hidden_sectors") || "[]"); }
  catch { return []; }
}
function setHiddenSectors(list) {
  localStorage.setItem("yalvon_hidden_sectors", JSON.stringify(list));
}

function wireSectorRows(root) {
  root.querySelectorAll("[data-sector-link]").forEach(row => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("[data-sector-dismiss]")) return;
      go("stocks");
      setTimeout(() => {
        if ($("sectorFilter")) {
          $("sectorFilter").value = row.dataset.sectorLink;
          applySymbolFilters();
        }
      }, 150);
    });
  });
  root.querySelectorAll("[data-sector-dismiss]").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const hidden = getHiddenSectors();
      hidden.push(btn.dataset.sectorDismiss);
      setHiddenSectors(hidden);
      loadExtras();
    });
  });
}

function macroMiniHtml(item) {
  return `
    <div class="macro-mini">
      <small>${esc(item.name)}</small>
      <strong>${esc(item.value)}</strong>
      <span>${esc(item.direction || item.note || "")}</span>
    </div>
  `;
}

function indexCardHtml(item) {
  const pct = Number(item.change_pct || 0);
  return `
    <div class="index-card ${pct >= 0 ? "tint-positive" : "tint-negative"}">
      <small>${esc(item.name || item.symbol)}</small>
      <strong>${Number(item.price).toLocaleString(undefined, {maximumFractionDigits:2})}</strong>
      <span class="${pct >= 0 ? "positive" : "negative"}">
        ${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%
      </span>
      <div class="card-sparkline">${seededSparkline(item.symbol || item.name, pct)}</div>
    </div>
  `;
}

function setRing(ringId, scoreId, labelId, score, label) {
  const ring = $(ringId);
  if (!ring) return;
  ring.style.setProperty("--val", Math.max(0, Math.min(100, Number(score))));
  if ($(scoreId)) $(scoreId).textContent = score;
  if ($(labelId)) $(labelId).textContent = label;
}

async function loadExtras() {
  const d = await getJSON("/api/extras");

  if ($("sectorList")) {
    const sortMode = $("sectorSort")?.value || "default";
    let sectors = d.sectors.slice();
    if (sortMode === "change_desc") sectors.sort((a, b) => b.change - a.change);
    if (sortMode === "change_asc") sectors.sort((a, b) => a.change - b.change);
    if (sortMode === "name_asc") sectors.sort((a, b) => a.sector.localeCompare(b.sector));

    $("sectorList").innerHTML = sectors.map(s => sectorRowHtml(s, false)).join("");
    wireSectorRows($("sectorList"));
    $("sectorCount").textContent = `${sectors.length} sectors`;
  }

  if ($("dashSectorStrip")) {
    const hidden = getHiddenSectors();
    const visible = d.sectors.filter(s => !hidden.includes(s.sector)).slice(0, 5);
    $("dashSectorStrip").innerHTML = visible.length
      ? visible.map(s => sectorRowHtml(s, true)).join("")
      : `<div class="empty-chart">All sectors hidden. <button class="link" id="resetHiddenSectorsBtn">Reset</button></div>`;
    wireSectorRows($("dashSectorStrip"));
    $("resetHiddenSectorsBtn")?.addEventListener("click", () => { setHiddenSectors([]); loadExtras(); });
  }

  if ($("macroCards")) {
    $("macroCards").innerHTML = d.macro.map(item => `
      <div class="card stat accent-card ${Number(item.supportive) === 1 ? "accent-teal" : (item.supportive === false ? "accent-rose" : "accent-gold")}">
        <small>${esc(item.name)}</small>
        <strong>${esc(item.value)}</strong>
        <span>${esc(item.direction ? `Trend: ${item.direction}` : item.note)}</span>
      </div>
    `).join("");
  }

  if ($("dashMacroStrip")) {
    $("dashMacroStrip").innerHTML = d.macro.map(macroMiniHtml).join("");
  }

  if (d.macro_signal && $("macroSignalRing")) {
    setRing(
      "macroSignalRing", "macroSignalScore", "macroSignalLabel",
      d.macro_signal.score, d.macro_signal.label
    );
    $("macroSignalNote").textContent =
      d.macro_signal.supportive.length || d.macro_signal.drag.length
        ? `Supportive: ${d.macro_signal.supportive.join(", ") || "—"} · Drag: ${d.macro_signal.drag.join(", ") || "—"}`
        : "Not enough directional data yet.";
  }

  if (d.indices) {
    if ($("dashIndexCards")) $("dashIndexCards").innerHTML = d.indices.map(indexCardHtml).join("");
    if ($("marketIndexCards")) $("marketIndexCards").innerHTML = d.indices.map(indexCardHtml).join("");
  }

  if (d.breadth) {
    if ($("dashNewHighs")) $("dashNewHighs").textContent = d.breadth.new_highs;
    if ($("dashNewLows")) $("dashNewLows").textContent = d.breadth.new_lows;
  }

  renderSentiment(d.fear_greed);

  if ($("globalSentimentGrid") && d.global_sentiment) {
    $("globalSentimentGrid").innerHTML = d.global_sentiment.map(m => `
      <div class="card global-sentiment-card" data-sentiment-key="${esc(m.key)}">
        <div class="sentiment-ring mini-sentiment-ring" style="--val:${m.score}"><strong>${m.score}</strong></div>
        <strong class="global-sentiment-name">${esc(m.name)}</strong>
        <span class="soft-chip">${esc(m.label)}</span>
      </div>
    `).join("");

    document.querySelectorAll("[data-sentiment-key]").forEach(card => {
      card.addEventListener("click", () => {
        const key = card.dataset.sentimentKey;
        const routes = { crypto: "crypto", forex: "forex", commodities: "commodities" };
        go(routes[key] || "market");
      });
    });
  }

  if ($("announcementList")) {
    $("announcementList").innerHTML = d.announcements.map(item => `
      <div class="announcement-card">
        <div class="announcement-symbol">${esc(item.symbol)}</div>
        <div>
          <strong>${esc(item.title)}</strong>
          <small>${esc(item.time)}</small>
        </div>
      </div>
    `).join("");
  }
}

async function loadTransactions() {
  const d = await getJSON("/api/transactions");

  $("txTable").innerHTML = d.map(x => `
    <tr>
      <td>${esc(x.date)}</td>
      <td class="symbol">${esc(x.symbol)}</td>
      <td>${esc(x.type)}</td>
      <td>${Number(x.quantity).toLocaleString()}</td>
      <td>${Number(x.price).toFixed(2)}</td>
      <td>${money(x.quantity * x.price)}</td>
    </tr>
  `).join("");
}

function openModal() {
  $("modal").classList.remove("hidden");
  $("formError").textContent = "";
  $("txDate").value = new Date().toISOString().slice(0,10);
}

function closeModal() {
  $("modal").classList.add("hidden");
}

async function saveTransaction() {
  try {
    const payload = {
      symbol: $("txSymbol").value,
      date: $("txDate").value,
      type: $("txType").value,
      quantity: Number($("txQty").value),
      price: Number($("txPrice").value),
    };

    const response = await fetch("/api/transactions", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Could not save transaction");
    }

    closeModal();
    await loadPortfolio();
    await loadTransactions();
    await go("portfolio");
  } catch (error) {
    $("formError").textContent = error.message;
  }
}

$("addBtn").onclick = openModal;
$("addBtn2").onclick = openModal;
$("addBtn3").onclick = openModal;
$("closeModal").onclick = closeModal;
$("saveTx").onclick = saveTransaction;
$("recordTodayBtn").onclick = recordToday;
$("refreshSymbolsBtn").onclick = refreshSymbols;
$("allStockSearch").oninput = applySymbolFilters;
$("sectorFilter").onchange = applySymbolFilters;
$("stockMoveFilter").onchange = applySymbolFilters;
$("sectorSort")?.addEventListener("change", loadExtras);

$("prevPageBtn").onclick = () => {
  symbolPage -= 1;
  renderSymbolPage();
};

$("nextPageBtn").onclick = () => {
  symbolPage += 1;
  renderSymbolPage();
};

setupNavigation();
setupHeaderSearch();
setupMobileNav();
renderStaticCharts();

loadPortfolio();
loadMarket();
loadWatchlist();
loadSymbols();
loadExtras();
loadMarket360();
loadDashboardHighlights();
loadDashboardTickers();


function renderSentiment(data) {
  if (!data) return;

  if ($("largeSentimentRing")) {
    setRing("largeSentimentRing", "largeSentimentScore", "largeSentimentLabel", data.score, data.label);

    $("sentimentComponents").innerHTML = data.components.map(c => `
      <div class="component-row">
        <span>${esc(c.name)}</span>
        <div class="component-bar"><i style="width:${c.score}%"></i></div>
        <b>${c.score}</b>
      </div>
    `).join("");
  }

  if ($("dashSentimentRing")) {
    setRing("dashSentimentRing", "dashSentimentScore", "dashSentimentLabel", data.score, data.label);
  }
}


/* =========================================================
   Markets page — Portfolio360-style expanded sections
   ========================================================= */

function miniBarChart(values, labels) {
  const max = Math.max(...values.map(v => Math.abs(v)), 1);
  return `
    <div class="mini-bars">
      ${values.map((v, i) => `
        <div class="mini-bar-col" title="${labels ? esc(labels[i]) : ""}: ${v}">
          <div class="mini-bar ${v >= 0 ? "up" : "down"}" style="height:${Math.max(6, Math.abs(v) / max * 60)}px"></div>
        </div>
      `).join("")}
    </div>
  `;
}

function wireMacroDetailCards(root) {
  if (!root) return;
  root.querySelectorAll("[data-macro-key]").forEach(card => {
    if (!card.dataset.macroKey) return;
    card.addEventListener("click", () => openMacroDetail(card.dataset.macroKey));
  });
}

async function openMacroDetail(key) {
  const modal = $("marketDetailModal");
  modal.classList.remove("hidden");
  $("marketDetailBody").innerHTML = `<div class="loading-panel">Loading…</div>`;

  try {
    const m = await getJSON(`/api/macro-detail/${encodeURIComponent(key)}`);
    $("marketDetailTitle").textContent = m.name;
    $("marketDetailBody").innerHTML = `
      <div class="market-detail-price-row">
        <strong>${esc(m.value)}</strong>
        <span class="${m.trend === "up" ? "positive" : (m.trend === "down" ? "negative" : "")}">
          ${m.trend === "up" ? "▲ Rising" : m.trend === "down" ? "▼ Falling" : "● Flat"}
        </span>
      </div>
      <p class="muted-note">Category: ${esc(m.category || "—")}</p>
      <p class="muted-note">${esc(m.note || "")}</p>
      <p class="muted-note market-detail-source">🟡 Development value — historical time-series graphs need a licensed macro data feed.</p>
    `;
  } catch (error) {
    $("marketDetailBody").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}

async function loadMacroPage() {
  if (!$("macroFullGrid")) return;
  try {
    const d = await getJSON("/api/market360");
    const categories = {};
    d.pakistan_profile.forEach(item => {
      const cat = item.category || "Other";
      (categories[cat] = categories[cat] || []).push(item);
    });

    $("macroFullGrid").innerHTML = Object.entries(categories).map(([cat, items]) => `
      <div class="macro-category-block">
        <h4>${esc(cat)}</h4>
        <div class="cards three">
          ${items.map(item => `
            <div class="card stat accent-card clickable-row ${item.trend === "up" ? "accent-rose" : (item.trend === "down" ? "accent-teal" : "accent-gold")}" data-macro-key="${esc(item.key || "")}">
              <small>${esc(item.name)}</small>
              <strong>${esc(item.value)}</strong>
              <span>${esc(item.note)}</span>
            </div>
          `).join("")}
        </div>
      </div>
    `).join("");
    wireMacroDetailCards($("macroFullGrid"));
  } catch (error) {
    $("macroFullGrid").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}

async function openFundHolders(symbol) {
  const modal = $("marketDetailModal");
  modal.classList.remove("hidden");
  $("marketDetailTitle").textContent = `${symbol} — Held By Funds`;
  $("marketDetailBody").innerHTML = `<div class="loading-panel">Loading…</div>`;

  try {
    const d = await getJSON(`/api/fund-holders/${encodeURIComponent(symbol)}`);
    if (!d.available) {
      $("marketDetailBody").innerHTML = `<div class="empty-chart">${esc(d.note)}</div>`;
      return;
    }
    $("marketDetailBody").innerHTML = `
      <p class="muted-note">${d.fund_count} funds hold ${esc(symbol)} (${esc(d.company)}):</p>
      <div class="fund-holders-list">
        ${d.funds.map(f => `
          <div class="mover-row">
            <div><strong>${esc(f.name)}</strong><small>${esc(f.amc)}</small></div>
            <div class="mover-right"><b>${esc(f.category)}</b></div>
          </div>
        `).join("")}
      </div>
      <p class="muted-note market-detail-source">🟡 ${esc(d.note)}</p>
    `;
  } catch (error) {
    $("marketDetailBody").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}

function wireMarketDetailCards(root) {
  if (!root) return;
  root.querySelectorAll("[data-market-key]").forEach(card => {
    card.addEventListener("click", () => openMarketDetail(card.dataset.marketKey));
  });
}

async function openMarketDetail(key) {
  const modal = $("marketDetailModal");
  modal.classList.remove("hidden");
  $("marketDetailBody").innerHTML = `<div class="loading-panel">Loading…</div>`;

  try {
    const m = await getJSON(`/api/market-detail/${encodeURIComponent(key)}`);
    const pct = Number(m.change_pct || 0);

    $("marketDetailTitle").textContent = m.name;
    $("marketDetailBody").innerHTML = `
      <div class="market-detail-price-row">
        <strong>${m.price != null ? Number(m.price).toLocaleString(undefined,{maximumFractionDigits:2}) : esc(m.label_value || "—")}</strong>
        <span class="${pct >= 0 ? "positive" : "negative"}">${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%${m.change_abs != null ? ` (${m.change_abs >= 0 ? "+" : ""}${m.change_abs})` : ""}</span>
      </div>
      ${m.range52w ? `
        <div class="range-block">
          <div class="range-label"><span>52-Week Range</span></div>
          <div class="detail-range-track">
            <i style="left:${m.price != null ? Math.min(100, Math.max(0, ((m.price - m.range52w[0]) / (m.range52w[1] - m.range52w[0])) * 100)) : 50}%"></i>
          </div>
          <div class="range-gauge-labels"><span>${m.range52w[0].toLocaleString()}</span><span>${m.range52w[1].toLocaleString()}</span></div>
        </div>
      ` : ""}
      <p class="muted-note">${esc(m.note || "")}</p>
      <p class="muted-note market-detail-source">${m.source === "Development value" || !m.source ? "🟡 Development value" : `🟢 ${esc(m.source)}`}</p>
    `;
  } catch (error) {
    $("marketDetailBody").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}

$("closeMarketDetailModal")?.addEventListener("click", () => $("marketDetailModal").classList.add("hidden"));
$("marketDetailModal")?.addEventListener("click", (e) => {
  if (e.target.id === "marketDetailModal") $("marketDetailModal").classList.add("hidden");
});

async function loadMarket360() {
  const d = await getJSON("/api/market360");

  // Dashboard's own "Today Across All Markets" + sentiment strip
  // (guarded independently — these elements only exist on the
  // Dashboard page, not the Markets page).
  if ($("dashWorldMarketCards")) {
    $("dashWorldMarketCards").innerHTML = d.multi_market.map(m => `
      <div class="index-card multi-market-card clickable-row ${m.tone === "up" ? "tint-positive" : "tint-negative"}" data-market-key="${esc(m.key)}">
        <small>${esc(m.name)}</small>
        <strong>${m.price != null ? Number(m.price).toLocaleString(undefined,{maximumFractionDigits:2}) : esc(m.label_value)}</strong>
        <span class="${m.tone === "up" ? "positive" : "negative"}">
          ${m.tone === "up" ? "▲" : "▼"} ${Math.abs(m.change_pct).toFixed(2)}%
        </span>
        <div class="card-sparkline">${seededSparkline(m.key || m.name, m.change_pct)}</div>
      </div>
    `).join("");
    wireMarketDetailCards($("dashWorldMarketCards"));
  }

  if ($("dashSentimentByMarket") && d.non_equity_sentiment) {
    const nes = d.non_equity_sentiment;
    $("dashSentimentByMarket").innerHTML = ["crypto", "forex", "commodities"].map(k => `
      <div class="mini-ring-block">
        <div class="sentiment-ring mini-sentiment-ring" style="--val:${nes[k].score}"><strong>${nes[k].score}</strong></div>
        <span>${k.charAt(0).toUpperCase()+k.slice(1)}</span>
        <small>${esc(nes[k].label)}</small>
      </div>
    `).join("");
  }

  // Full Portfolio360-style detail block: render for the Markets page
  // (plain ids) when present, and for the Dashboard's "Complete Market
  // Detail" section (ids suffixed "Home") when present. Both draw from
  // the same single /api/market360 + /api/extras fetch.
  const extras = await getJSON("/api/extras");

  if ($("multiMarketCards")) renderMarket360Detail(d, extras, "");
  if ($("multiMarketCardsHome")) renderMarket360Detail(d, extras, "Home");
}

function renderMarket360Detail(d, extras, suffix) {
  // Risk sentiment
  if (d.risk_sentiment) {
    const pct = Math.round(((d.risk_sentiment.composite + 100) / 200) * 100);
    setRing("riskSentimentRing" + suffix, "riskSentimentScore" + suffix, null, pct, "");
    $("riskSentimentLabel" + suffix).textContent = d.risk_sentiment.label;
    $("riskSentimentNote" + suffix).textContent = d.risk_sentiment.note;
  }

  // Multi-market cards
  $("multiMarketCards" + suffix).innerHTML = d.multi_market.map(m => `
    <div class="index-card multi-market-card clickable-row ${m.tone === "up" ? "tint-positive" : "tint-negative"}" data-market-key="${esc(m.key)}">
      <div class="multi-market-card-head">
        <small>${esc(m.name)}</small>
        <span class="data-badge ${m.source === "Development value" ? "badge-dev" : "badge-live"}">
          ${m.source === "Development value" ? "DEV" : "LIVE"}
        </span>
      </div>
      <strong>${m.price != null ? Number(m.price).toLocaleString(undefined,{maximumFractionDigits:2}) : esc(m.label_value)}</strong>
      <span class="${m.tone === "up" ? "positive" : "negative"}">
        ${m.tone === "up" ? "▲" : "▼"} ${Math.abs(m.change_pct).toFixed(2)}%
        ${m.change_abs != null ? ` (${m.change_abs >= 0 ? "+" : ""}${m.change_abs})` : ""}
      </span>
      <div class="card-sparkline">${seededSparkline(m.key || m.name, m.change_pct)}</div>
    </div>
  `).join("");
  wireMarketDetailCards($("multiMarketCards" + suffix));

  if (!d.live_data_enabled && $("liveDataNotice" + suffix)) {
    $("liveDataNotice" + suffix).classList.remove("hidden");
  }

  // Cross-asset signals
  $("crossAssetSignals" + suffix).innerHTML = d.cross_asset_signals.map(s => `
    <div class="card signal-card">
      <small>${esc(s.title)}</small>
      <strong class="${s.tone === "up" ? "positive" : "negative"}">${esc(s.read)}</strong>
      <p>${esc(s.note)}</p>
    </div>
  `).join("");

  // Cross-asset highlights
  const h = d.cross_asset_highlights;
  $("crossAssetHighlights" + suffix).innerHTML = `
    <div class="card">
      <div class="card-head"><h3>Cryptocurrencies</h3></div>
      <div class="mini-stat-row"><span>Total Market Cap</span><b>${esc(h.crypto.total_market_cap)} <small class="positive">+${h.crypto.market_cap_change}%</small></b></div>
      <div class="mini-stat-row"><span>Fear &amp; Greed</span><b>${h.crypto.fear_greed} <small>${esc(h.crypto.fear_greed_label)}</small></b></div>
      <div class="mini-stat-row"><span>BTC Dominance</span><b>${esc(h.crypto.btc_dominance)}</b></div>
      <div class="mini-stat-row"><span>Breadth (24h)</span><b>${h.crypto.breadth_up} up / ${h.crypto.breadth_down} down</b></div>
      <div class="mini-stat-row"><span>Top</span><b>${esc(h.crypto.top_symbol)} <small class="positive">+${h.crypto.top_change}%</small></b></div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Forex</h3></div>
      <div class="mini-stat-row"><span>Strongest</span><b>${esc(h.forex.strongest)} <small class="positive">+${h.forex.strongest_change}%</small></b></div>
      <div class="mini-stat-row"><span>Weakest</span><b>${esc(h.forex.weakest)} <small class="negative">${h.forex.weakest_change}%</small></b></div>
      <div class="mini-stat-row"><span>USD / PKR</span><b>${h.forex.usd_pkr} <small class="positive">+${h.forex.usd_pkr_change}%</small></b></div>
      <div class="mini-stat-row"><span>Breadth (1D)</span><b>${h.forex.breadth_up} up / ${h.forex.breadth_down} down</b></div>
      <div class="mini-stat-row"><span>Top</span><b>${esc(h.forex.top_symbol)} <small class="positive">+${h.forex.top_change}%</small></b></div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Commodities</h3></div>
      <div class="mini-stat-row"><span>Best Sector</span><b>${esc(h.commodities.best_sector)} <small class="positive">+${h.commodities.best_change}%</small></b></div>
      <div class="mini-stat-row"><span>Worst Sector</span><b>${esc(h.commodities.worst_sector)} <small class="negative">${h.commodities.worst_change}%</small></b></div>
      <div class="mini-stat-row"><span>Gold</span><b>${esc(h.commodities.gold)} <small class="positive">+${h.commodities.gold_change}%</small></b></div>
      <div class="mini-stat-row"><span>Breadth (1D)</span><b>${h.commodities.breadth_up} up / ${h.commodities.breadth_down} down</b></div>
      <div class="mini-stat-row"><span>Top</span><b>${esc(h.commodities.top_symbol)} <small class="positive">+${h.commodities.top_change}%</small></b></div>
    </div>
  `;

  // Trending stocks
  $("trendingWindow" + suffix).textContent = d.trending_stocks.window;
  const trendRow = item => `
    <div class="mover-row">
      <div>
        <strong>${esc(item.symbol)}</strong>
        <small>${esc(item.sector)}</small>
      </div>
      <div class="mover-right">
        <b class="${item.change >= 0 ? "positive" : "negative"}">${item.change >= 0 ? "+" : ""}${item.change.toFixed(2)}%</b>
        <small>${esc(item.streak)}${item.steady ? " · Steady" : ""}</small>
      </div>
    </div>
  `;
  $("trendingGainers" + suffix).innerHTML = d.trending_stocks.gainers.map(trendRow).join("");
  $("trendingLosers" + suffix).innerHTML = d.trending_stocks.losers.map(trendRow).join("");

  // 52 week
  const weekRow = item => `
    <div class="mover-row">
      <div><strong>${esc(item.symbol)}</strong><small>${esc(item.company)}</small></div>
      <div class="mover-right">
        <b>${item.price}</b>
        <small class="${item.change_pct >= 0 ? "positive" : "negative"}">${item.change_pct >= 0 ? "+" : ""}${item.change_pct}%</small>
      </div>
    </div>
  `;
  $("week52Highs" + suffix).innerHTML = d.week52.highs.length
    ? d.week52.highs.map(weekRow).join("")
    : `<div class="empty-chart">Quiet day otherwise</div>`;
  $("week52Lows" + suffix).innerHTML = d.week52.lows.length
    ? d.week52.lows.map(weekRow).join("")
    : `<div class="empty-chart">Quiet day otherwise</div>`;

  // Fund flows
  const ff = d.fund_flows;
  $("fundFlowsSummary" + suffix).innerHTML = `
    <div class="flow-summary-item">
      <span>Foreign Investors (FIPI)</span>
      <strong class="${ff.foreign_mn >= 0 ? "positive" : "negative"}">${ff.foreign_mn >= 0 ? "+" : ""}$${ff.foreign_mn.toFixed(2)} mn</strong>
      <small>${esc(ff.session)}</small>
    </div>
    <div class="flow-summary-item">
      <span>Local Investors (LIPI)</span>
      <strong class="${ff.local_mn >= 0 ? "positive" : "negative"}">${ff.local_mn >= 0 ? "+" : ""}$${ff.local_mn.toFixed(2)} mn</strong>
      <small>Every foreign buy is a local sell</small>
    </div>
    <p>${esc(ff.note)}</p>
  `;
  $("fundFlowsMatrix" + suffix).innerHTML = ff.sectors.map(row => `
    <tr>
      <td>${esc(row.sector)}</td>
      ${["foreign","individuals","mutual_funds","banks","companies","brokers","insurance","other"].map(k => {
        const v = row[k];
        return `<td class="${v > 0 ? "positive" : (v < 0 ? "negative" : "")}">${v === 0 ? "—" : (v > 0 ? "+" : "") + v}</td>`;
      }).join("")}
    </tr>
  `).join("");
  $("fundFlowsChart" + suffix).innerHTML =
    `<div class="mini-bar-caption">Foreign net flow, last ${ff.net_flow_30d.length} sessions (USD mn)</div>` +
    miniBarChart(ff.net_flow_30d);

  // Insider activity
  const ia = d.insider_activity;
  $("insiderNote" + suffix).textContent = ia.note;
  const insiderRow = item => `
    <div class="mover-row">
      <div><strong>${esc(item.symbol)}</strong><small>${esc(item.company)}</small></div>
      <div class="mover-right"><b>${esc(item.value)}</b><small>${item.filings} filing${item.filings === 1 ? "" : "s"}</small></div>
    </div>
  `;
  $("insiderBuying" + suffix).innerHTML = ia.top_buying.map(insiderRow).join("");
  $("insiderSelling" + suffix).innerHTML = ia.top_selling.map(insiderRow).join("");
  $("insiderMonthlyChart" + suffix).innerHTML =
    `<div class="mini-bar-caption">Bought vs sold by month</div>` +
    miniBarChart(ia.monthly.map(m => m.bought - m.sold), ia.monthly.map(m => m.month));

  // Sentiment history
  const sh = d.sentiment_history;
  setRing("mktSentimentRing" + suffix, "mktSentimentScore" + suffix, null, sh.previous_close, "");
  $("sentimentHistoryList" + suffix).innerHTML = `
    <div><span>Previous Close</span><b>${sh.previous_close} <small>${esc(sh.previous_close_label)}</small></b></div>
    <div><span>1 Week Ago</span><b>${sh.week_ago} <small>${esc(sh.week_ago_label)}</small></b></div>
    <div><span>1 Month Ago</span><b>${sh.month_ago} <small>${esc(sh.month_ago_label)}</small></b></div>
    <div><span>1 Year Ago</span><b>${sh.year_ago ?? "—"} <small>${esc(sh.year_ago_label)}</small></b></div>
  `;
  $("sentimentReadText" + suffix).textContent = sh.read;
  const total = sh.advancing + sh.flat + sh.declining;
  $("breadthBar" + suffix).innerHTML = `
    <div class="breadth-track">
      <i class="up" style="width:${(sh.advancing/total*100).toFixed(1)}%"></i>
      <i class="down" style="width:${(sh.declining/total*100).toFixed(1)}%"></i>
    </div>
    <div class="breadth-caption">
      <span class="positive">${sh.advancing} advancing</span>
      <span>${sh.flat} flat</span>
      <span class="negative">${sh.declining} declining</span>
    </div>
  `;

  // Non-equity sentiment
  const nes = d.non_equity_sentiment;
  $("nonEquitySentiment" + suffix).innerHTML = ["crypto","forex","commodities"].map(k => `
    <div class="mini-ring-block">
      <div class="sentiment-ring mini-sentiment-ring" style="--val:${nes[k].score}"><strong>${nes[k].score}</strong></div>
      <span>${k.charAt(0).toUpperCase()+k.slice(1)}</span>
      <small>${esc(nes[k].label)}</small>
    </div>
  `).join("");

  const bp = d.breadth_pulse;
  $("breadthPulse" + suffix).innerHTML = ["crypto","forex","commodities"].map(k => `
    <div class="pulse-row">
      <span>${k.charAt(0).toUpperCase()+k.slice(1)}</span>
      <div class="pulse-track"><i style="width:${bp[k]}%"></i></div>
      <b>${bp[k]}% up</b>
    </div>
  `).join("");

  // Top stocks three ways
  const listRow = (item, valueLabel) => `
    <div class="mover-row">
      <div><strong>${esc(item.symbol)}</strong><small>${esc(item.company)}</small></div>
      <div class="mover-right"><b>${valueLabel(item)}</b></div>
    </div>
  `;
  $("topStocksFavorites" + suffix).innerHTML = d.top_stocks_three_ways.investor_favorites
    .map(item => listRow(item, i => `#${i.rank} · ${i.marks}`)).join("");
  $("topStocksFundamentals" + suffix).innerHTML = d.top_stocks_three_ways.fundamentals_top
    .map(item => listRow(item, i => i.score)).join("");
  $("topStocksFundHoldings" + suffix).innerHTML = d.top_stocks_three_ways.fund_holdings
    .map(item => `
      <div class="mover-row clickable-row" data-fund-holders="${esc(item.symbol)}">
        <div><strong>${esc(item.symbol)}</strong><small>${esc(item.company)}</small></div>
        <div class="mover-right"><b>${item.funds} funds →</b></div>
      </div>
    `).join("");
  document.querySelectorAll(`#topStocksFundHoldings${suffix} [data-fund-holders]`).forEach(row => {
    row.addEventListener("click", () => openFundHolders(row.dataset.fundHolders));
  });

  // Levels to play
  const ls = d.levels_to_play.summary;
  const lsTotal = ls.strong_bearish + ls.bearish + ls.neutral + ls.bullish + ls.strong_bullish;
  $("levelsSummary" + suffix).innerHTML = `
    <div class="levels-track">
      <i class="l-strong-bear" style="width:${ls.strong_bearish/lsTotal*100}%"></i>
      <i class="l-bear" style="width:${ls.bearish/lsTotal*100}%"></i>
      <i class="l-neutral" style="width:${ls.neutral/lsTotal*100}%"></i>
      <i class="l-bull" style="width:${ls.bullish/lsTotal*100}%"></i>
      <i class="l-strong-bull" style="width:${ls.strong_bullish/lsTotal*100}%"></i>
    </div>
    <div class="levels-legend">
      <span><i class="l-strong-bear"></i> Strong Bearish ${ls.strong_bearish}</span>
      <span><i class="l-bear"></i> Bearish ${ls.bearish}</span>
      <span><i class="l-neutral"></i> Neutral ${ls.neutral}</span>
      <span><i class="l-bull"></i> Bullish ${ls.bullish}</span>
      <span><i class="l-strong-bull"></i> Strong Bullish ${ls.strong_bullish}</span>
    </div>
  `;
  $("levelsStocks" + suffix).innerHTML = d.levels_to_play.stocks.map(item => `
    <div class="mover-row">
      <div><strong>${esc(item.symbol)}</strong><small>${esc(item.conviction)} · ${esc(item.setup)}</small></div>
      <div class="mover-right"><b>${item.level}</b><small>${esc(item.note)}</small></div>
    </div>
  `).join("");

  // Seasonality
  $("seasonalityHead" + suffix).innerHTML = `<th>Metric</th>` + d.seasonality.months.map(m => `<th>${m}</th>`).join("");
  $("seasonalityRow" + suffix).innerHTML = `<td>Median</td>` + d.seasonality.median.map((v,i) => `
    <td class="${v >= 0 ? "positive" : "negative"}">${v >= 0 ? "+" : ""}${v}%<br><small>${d.seasonality.hit_rate[i]}</small></td>
  `).join("");
  $("seasonalStocks" + suffix).innerHTML = d.seasonality.top_seasonal_stocks.map(item => `
    <div class="mover-row">
      <div><strong>${esc(item.symbol)}</strong><small>${esc(item.record)}</small></div>
      <div class="mover-right"><b class="positive">+${item.median}%</b><small>Worst: ${esc(item.worst)}</small></div>
    </div>
  `).join("");

  // Pakistan profile
  $("pakistanProfileCards" + suffix).innerHTML = d.pakistan_profile.map(item => `
    <div class="card stat accent-card clickable-row ${item.trend === "up" ? "accent-rose" : (item.trend === "down" ? "accent-teal" : "accent-gold")}" data-macro-key="${esc(item.key || "")}">
      <small>${esc(item.name)}</small>
      <strong>${esc(item.value)}</strong>
      <span>${esc(item.note)}</span>
    </div>
  `).join("");
  wireMacroDetailCards($("pakistanProfileCards" + suffix));

  // News / announcements / payouts (extras passed in from the caller,
  // fetched once and reused for both the Markets page and Dashboard).
  $("marketAnnouncementList" + suffix).innerHTML = extras.announcements.map(item => `
    <div class="announcement-card">
      <div class="announcement-symbol">${esc(item.symbol)}</div>
      <div><strong>${esc(item.title)}</strong><small>${esc(item.time)}</small></div>
    </div>
  `).join("");
  $("marketNewsList" + suffix).innerHTML = extras.announcements.map(item => `
    <div class="mover-row">
      <div><strong>${esc(item.title)}</strong><small>${esc(item.symbol)} · ${esc(item.time)}</small></div>
    </div>
  `).join("") || `<div class="empty-chart">No news cached yet.</div>`;

  $("upcomingPayouts" + suffix).innerHTML = d.upcoming_payouts.map(item => `
    <div class="mover-row">
      <div><strong>${esc(item.symbol)}</strong><small>Ex Date ${esc(item.ex_date)}</small></div>
      <div class="mover-right"><b class="positive">${esc(item.amount)}</b></div>
    </div>
  `).join("");

  $("calendarEvents" + suffix).innerHTML = d.calendar_events.map(item => `
    <div class="card calendar-event-card">
      <small class="positive">${esc(item.date)}</small>
      <strong>${esc(item.title)}</strong>
      <span class="soft-chip">${esc(item.tag)}</span>
    </div>
  `).join("");
}


/* =========================================================
   Journal page
   ========================================================= */

async function loadJournal() {
  const d = await getJSON("/api/journal");

  $("journalArticles").innerHTML = d.articles.map(a => `
    <div class="card journal-article-card">
      <span class="soft-chip">${esc(a.category)}</span>
      <h3>${esc(a.title)}</h3>
      <p>${esc(a.blurb)}</p>
    </div>
  `).join("");

  $("journalPodcasts").innerHTML = d.podcasts.map(p => `
    <div class="mover-row">
      <div><strong>${esc(p.title)}</strong><small>${esc(p.guest)}</small></div>
      <div class="mover-right"><b>${esc(p.episode)}</b></div>
    </div>
  `).join("");
}


/* =========================================================
   Tools page — working calculators
   ========================================================= */

const TOOL_RENDERERS = {
  "market-calc": () => `
    <h3>Stock Market Calculator</h3>
    <p class="muted-note">One tool, several modes — pick what you need below.</p>
    <label>Calculator
      <select id="mc_mode" onchange="renderMarketCalcMode()">
        <option value="pl">Profit / Loss</option>
        <option value="breakeven">Break-Even Price</option>
        <option value="target">Target Price (from % gain)</option>
        <option value="position">Position Sizing (risk-based)</option>
        <option value="avgcost">Average Cost (adding shares)</option>
        <option value="cgt">Capital Gains Tax Estimate</option>
      </select>
    </label>
    <div id="mc_fields"></div>
    <button class="primary" onclick="calcMarketCalc()">Calculate</button>
    <div id="mc_result" class="tool-result"></div>
  `,
  zakat: () => `
    <h3>Zakat Calculator</h3>
    <p class="muted-note">A simple 2.5% nisab-based estimate. Not religious advice — confirm specifics with your scholar.</p>
    <label>Cash &amp; bank balances (PKR)<input id="zk_cash" type="number" value="0"></label>
    <label>Portfolio market value (PKR)<input id="zk_portfolio" type="number" value="0"></label>
    <label>Other zakatable assets (PKR)<input id="zk_other" type="number" value="0"></label>
    <label>Liabilities due within a year (PKR)<input id="zk_liab" type="number" value="0"></label>
    <button class="primary" onclick="calcZakat()">Calculate</button>
    <div id="zk_result" class="tool-result"></div>
  `,
  purification: () => `
    <h3>Dividend Purification</h3>
    <p class="muted-note">Charity due from PSX dividends, using a published purification rate for the stock.</p>
    <label>Total dividend received (PKR)<input id="pu_div" type="number" value="0"></label>
    <label>Published purification rate (%)<input id="pu_rate" type="number" value="5" step="0.1"></label>
    <button class="primary" onclick="calcPurification()">Calculate</button>
    <div id="pu_result" class="tool-result"></div>
  `,
  fire: () => `
    <h3>FIRE Calculator</h3>
    <label>Annual expenses (PKR)<input id="fi_expenses" type="number" value="1200000"></label>
    <label>Current invested savings (PKR)<input id="fi_current" type="number" value="500000"></label>
    <label>Monthly contribution (PKR)<input id="fi_monthly" type="number" value="50000"></label>
    <label>Expected annual return (%)<input id="fi_return" type="number" value="12" step="0.1"></label>
    <label>Safe withdrawal rate (%)<input id="fi_swr" type="number" value="4" step="0.1"></label>
    <button class="primary" onclick="calcFire()">Calculate</button>
    <div id="fi_result" class="tool-result"></div>
  `,
  goal: () => `
    <h3>Goal Planner</h3>
    <label>Target amount (PKR)<input id="gp_target" type="number" value="2000000"></label>
    <label>Amount already saved (PKR)<input id="gp_current" type="number" value="200000"></label>
    <label>Years to reach goal<input id="gp_years" type="number" value="5" step="0.5"></label>
    <label>Expected annual return (%)<input id="gp_return" type="number" value="10" step="0.1"></label>
    <button class="primary" onclick="calcGoal()">Calculate</button>
    <div id="gp_result" class="tool-result"></div>
  `,
  sip: () => `
    <h3>SIP Calculator</h3>
    <label>Monthly investment (PKR)<input id="sip_amount" type="number" value="20000"></label>
    <label>Expected annual return (%)<input id="sip_return" type="number" value="12" step="0.1"></label>
    <label>Duration (years)<input id="sip_years" type="number" value="10" step="0.5"></label>
    <button class="primary" onclick="calcSip()">Calculate</button>
    <div id="sip_result" class="tool-result"></div>
  `,
  dcf: () => `
    <h3>DCF Calculator</h3>
    <p class="muted-note">A simplified two-stage discounted cash flow, for quick sanity checks — not a substitute for full modeling.</p>
    <label>Current free cash flow (PKR mn)<input id="dcf_fcf" type="number" value="1000"></label>
    <label>Growth rate, years 1–5 (%)<input id="dcf_growth" type="number" value="12" step="0.1"></label>
    <label>Terminal growth rate (%)<input id="dcf_terminal" type="number" value="4" step="0.1"></label>
    <label>Discount rate / WACC (%)<input id="dcf_wacc" type="number" value="15" step="0.1"></label>
    <label>Shares outstanding (mn)<input id="dcf_shares" type="number" value="500"></label>
    <button class="primary" onclick="calcDcf()">Calculate</button>
    <div id="dcf_result" class="tool-result"></div>
  `,
  "compare-stocks": () => `
    <h3>Compare Stocks</h3>
    <p class="muted-note">Enter up to 4 PSX symbols, comma-separated.</p>
    <label>Symbols<input id="cmp_symbols" placeholder="FFC, UBL, OGDC"></label>
    <button class="primary" onclick="calcCompareStocks()">Compare</button>
    <div id="cmp_result" class="tool-result"></div>
  `,
  "compare-funds": () => `
    <h3>Compare Funds</h3>
    <p class="muted-note">Development fund list — NAV, YTD return and AUM.</p>
    <div id="cmpf_result" class="tool-result"></div>
  `,
};

async function loadTools() {
  const d = await getJSON("/api/tools");
  window._toolFunds = d.funds;

  $("toolCatalog").innerHTML = d.catalog.map(t => `
    <div class="card tool-card" data-tool="${t.key}">
      <h3>${esc(t.name)}</h3>
      <p>${esc(t.blurb)}</p>
    </div>
  `).join("");

  document.querySelectorAll(".tool-card").forEach(card => {
    card.addEventListener("click", () => openTool(card.dataset.tool));
  });
}

function openTool(key) {
  const box = $("toolWorkspace");
  box.classList.remove("hidden");
  box.innerHTML = TOOL_RENDERERS[key] ? TOOL_RENDERERS[key]() : "<p>Coming soon.</p>";
  box.scrollIntoView({behavior:"smooth", block:"start"});

  if (key === "compare-funds") calcCompareFunds();
  if (key === "market-calc") renderMarketCalcMode();
}

const MARKET_CALC_MODES = {
  pl: {
    fields: `
      <label>Buy price (per share)<input id="mc_buy" type="number" value="100" step="0.01"></label>
      <label>Sell price (per share)<input id="mc_sell" type="number" value="110" step="0.01"></label>
      <label>Quantity<input id="mc_qty" type="number" value="100"></label>
      <label>Brokerage / commission, each side (%)<input id="mc_brokerage" type="number" value="0.15" step="0.01"></label>
    `,
    calc: () => {
      const buy = Number($("mc_buy").value || 0);
      const sell = Number($("mc_sell").value || 0);
      const qty = Number($("mc_qty").value || 0);
      const brokeragePct = Number($("mc_brokerage").value || 0) / 100;

      const buyCost = buy * qty * (1 + brokeragePct);
      const sellProceeds = sell * qty * (1 - brokeragePct);
      const pl = sellProceeds - buyCost;
      const plPct = buyCost ? (pl / buyCost) * 100 : 0;

      return `
        <div class="mini-stat-row"><span>Total buy cost (incl. brokerage)</span><b>${money(buyCost)}</b></div>
        <div class="mini-stat-row"><span>Total sell proceeds (after brokerage)</span><b>${money(sellProceeds)}</b></div>
        <div class="mini-stat-row"><span>Profit / Loss</span><b class="${pl >= 0 ? "positive" : "negative"}">${pl >= 0 ? "+" : "-"}${money(Math.abs(pl))}</b></div>
        <div class="mini-stat-row"><span>Return</span><b class="${pl >= 0 ? "positive" : "negative"}">${plPct >= 0 ? "+" : ""}${plPct.toFixed(2)}%</b></div>
      `;
    },
  },
  breakeven: {
    fields: `
      <label>Buy price (per share)<input id="mc_buy2" type="number" value="100" step="0.01"></label>
      <label>Brokerage / commission, each side (%)<input id="mc_brokerage2" type="number" value="0.15" step="0.01"></label>
    `,
    calc: () => {
      const buy = Number($("mc_buy2").value || 0);
      const brokeragePct = Number($("mc_brokerage2").value || 0) / 100;
      const breakeven = (buy * (1 + brokeragePct)) / (1 - brokeragePct);

      return `
        <div class="mini-stat-row"><span>Break-even sell price</span><b>${breakeven.toFixed(2)}</b></div>
        <div class="mini-stat-row"><span>Minimum move needed</span><b>${(((breakeven - buy) / buy) * 100).toFixed(2)}%</b></div>
      `;
    },
  },
  target: {
    fields: `
      <label>Current price<input id="mc_current" type="number" value="100" step="0.01"></label>
      <label>Desired gain (%)<input id="mc_gain" type="number" value="15" step="0.1"></label>
    `,
    calc: () => {
      const current = Number($("mc_current").value || 0);
      const gain = Number($("mc_gain").value || 0) / 100;
      const target = current * (1 + gain);

      return `
        <div class="mini-stat-row"><span>Target price</span><b class="positive">${target.toFixed(2)}</b></div>
        <div class="mini-stat-row"><span>Price move needed</span><b>${(target - current).toFixed(2)}</b></div>
      `;
    },
  },
  position: {
    fields: `
      <label>Account size (PKR)<input id="mc_account" type="number" value="500000"></label>
      <label>Risk per trade (%)<input id="mc_risk" type="number" value="1" step="0.1"></label>
      <label>Entry price<input id="mc_entry" type="number" value="100" step="0.01"></label>
      <label>Stop-loss price<input id="mc_stop" type="number" value="95" step="0.01"></label>
    `,
    calc: () => {
      const account = Number($("mc_account").value || 0);
      const riskPct = Number($("mc_risk").value || 0) / 100;
      const entry = Number($("mc_entry").value || 0);
      const stop = Number($("mc_stop").value || 0);

      const riskAmount = account * riskPct;
      const perShareRisk = Math.abs(entry - stop);
      const shares = perShareRisk > 0 ? Math.floor(riskAmount / perShareRisk) : 0;

      return `
        <div class="mini-stat-row"><span>Amount at risk</span><b>${money(riskAmount)}</b></div>
        <div class="mini-stat-row"><span>Risk per share</span><b>${perShareRisk.toFixed(2)}</b></div>
        <div class="mini-stat-row"><span>Suggested position size</span><b class="positive">${shares.toLocaleString()} shares</b></div>
        <div class="mini-stat-row"><span>Position cost</span><b>${money(shares * entry)}</b></div>
      `;
    },
  },
  avgcost: {
    fields: `
      <label>Existing quantity<input id="mc_oldqty" type="number" value="100"></label>
      <label>Existing average cost<input id="mc_oldavg" type="number" value="100" step="0.01"></label>
      <label>New quantity being bought<input id="mc_newqty" type="number" value="50"></label>
      <label>New buy price<input id="mc_newprice" type="number" value="90" step="0.01"></label>
    `,
    calc: () => {
      const oldQty = Number($("mc_oldqty").value || 0);
      const oldAvg = Number($("mc_oldavg").value || 0);
      const newQty = Number($("mc_newqty").value || 0);
      const newPrice = Number($("mc_newprice").value || 0);

      const totalQty = oldQty + newQty;
      const newAvg = totalQty ? ((oldQty * oldAvg) + (newQty * newPrice)) / totalQty : 0;

      return `
        <div class="mini-stat-row"><span>New total quantity</span><b>${totalQty.toLocaleString()}</b></div>
        <div class="mini-stat-row"><span>New average cost</span><b>${newAvg.toFixed(2)}</b></div>
        <div class="mini-stat-row"><span>Total invested</span><b>${money(totalQty * newAvg)}</b></div>
      `;
    },
  },
  cgt: {
    fields: `
      <label>Sell price<input id="mc_cgt_sell" type="number" value="120" step="0.01"></label>
      <label>Buy price<input id="mc_cgt_buy" type="number" value="100" step="0.01"></label>
      <label>Quantity<input id="mc_cgt_qty" type="number" value="100"></label>
      <label>CGT rate (%) — check current PSX/FBR rate for your holding period<input id="mc_cgt_rate" type="number" value="15" step="0.1"></label>
    `,
    calc: () => {
      const sell = Number($("mc_cgt_sell").value || 0);
      const buy = Number($("mc_cgt_buy").value || 0);
      const qty = Number($("mc_cgt_qty").value || 0);
      const rate = Number($("mc_cgt_rate").value || 0) / 100;

      const gain = Math.max(0, (sell - buy) * qty);
      const tax = gain * rate;

      return `
        <div class="mini-stat-row"><span>Capital gain</span><b class="positive">${money(gain)}</b></div>
        <div class="mini-stat-row"><span>Estimated CGT due</span><b class="negative">${money(tax)}</b></div>
        <div class="mini-stat-row"><span>Net proceeds after CGT</span><b>${money(gain - tax)}</b></div>
        <p class="muted-note">PSX capital gains tax rates depend on your holding period and filer status — this is a flat-rate estimate only. Confirm the current rate with FBR/your broker before relying on it.</p>
      `;
    },
  },
};

function renderMarketCalcMode() {
  const mode = $("mc_mode").value;
  $("mc_fields").innerHTML = MARKET_CALC_MODES[mode].fields;
  $("mc_result").innerHTML = "";
}

function calcMarketCalc() {
  const mode = $("mc_mode").value;
  $("mc_result").innerHTML = MARKET_CALC_MODES[mode].calc();
}

function calcZakat() {
  const cash = Number($("zk_cash").value || 0);
  const portfolio = Number($("zk_portfolio").value || 0);
  const other = Number($("zk_other").value || 0);
  const liab = Number($("zk_liab").value || 0);

  const zakatable = Math.max(0, cash + portfolio + other - liab);
  const due = zakatable * 0.025;

  $("zk_result").innerHTML = `
    <div class="mini-stat-row"><span>Net zakatable assets</span><b>${money(zakatable)}</b></div>
    <div class="mini-stat-row"><span>Zakat due (2.5%)</span><b class="positive">${money(due)}</b></div>
  `;
}

function calcPurification() {
  const div = Number($("pu_div").value || 0);
  const rate = Number($("pu_rate").value || 0);
  const due = div * (rate / 100);

  $("pu_result").innerHTML = `
    <div class="mini-stat-row"><span>Purification due</span><b class="positive">${money(due)}</b></div>
    <div class="mini-stat-row"><span>Net dividend after purification</span><b>${money(div - due)}</b></div>
  `;
}

function calcFire() {
  const expenses = Number($("fi_expenses").value || 0);
  const current = Number($("fi_current").value || 0);
  const monthly = Number($("fi_monthly").value || 0);
  const ret = Number($("fi_return").value || 0) / 100;
  const swr = Number($("fi_swr").value || 0) / 100;

  const target = expenses / (swr || 0.04);
  const monthlyRate = ret / 12;
  let balance = current;
  let months = 0;

  while (balance < target && months < 1200) {
    balance = balance * (1 + monthlyRate) + monthly;
    months += 1;
  }

  $("fi_result").innerHTML = `
    <div class="mini-stat-row"><span>FIRE number</span><b>${money(target)}</b></div>
    <div class="mini-stat-row"><span>Time to reach it</span><b>${months >= 1200 ? "200+ years — increase savings" : `${Math.floor(months/12)}y ${months%12}m`}</b></div>
  `;
}

function calcGoal() {
  const target = Number($("gp_target").value || 0);
  const current = Number($("gp_current").value || 0);
  const years = Number($("gp_years").value || 0);
  const ret = Number($("gp_return").value || 0) / 100;

  const months = Math.max(1, years * 12);
  const monthlyRate = ret / 12;
  const futureValueOfCurrent = current * Math.pow(1 + monthlyRate, months);
  const remaining = Math.max(0, target - futureValueOfCurrent);

  const monthlyContribution = monthlyRate > 0
    ? remaining * monthlyRate / (Math.pow(1 + monthlyRate, months) - 1)
    : remaining / months;

  $("gp_result").innerHTML = `
    <div class="mini-stat-row"><span>Required monthly contribution</span><b>${money(monthlyContribution)}</b></div>
    <div class="mini-stat-row"><span>Current savings will grow to</span><b>${money(futureValueOfCurrent)}</b></div>
  `;
}

function calcSip() {
  const amount = Number($("sip_amount").value || 0);
  const ret = Number($("sip_return").value || 0) / 100;
  const years = Number($("sip_years").value || 0);

  const months = years * 12;
  const monthlyRate = ret / 12;
  const futureValue = monthlyRate > 0
    ? amount * ((Math.pow(1 + monthlyRate, months) - 1) / monthlyRate) * (1 + monthlyRate)
    : amount * months;
  const invested = amount * months;

  $("sip_result").innerHTML = `
    <div class="mini-stat-row"><span>Total invested</span><b>${money(invested)}</b></div>
    <div class="mini-stat-row"><span>Projected value</span><b class="positive">${money(futureValue)}</b></div>
    <div class="mini-stat-row"><span>Projected gain</span><b class="positive">${money(futureValue - invested)}</b></div>
  `;
}

function calcDcf() {
  const fcf = Number($("dcf_fcf").value || 0);
  const growth = Number($("dcf_growth").value || 0) / 100;
  const terminal = Number($("dcf_terminal").value || 0) / 100;
  const wacc = Number($("dcf_wacc").value || 0) / 100;
  const shares = Number($("dcf_shares").value || 1);

  let pv = 0;
  let flow = fcf;

  for (let year = 1; year <= 5; year++) {
    flow = flow * (1 + growth);
    pv += flow / Math.pow(1 + wacc, year);
  }

  const terminalValue = (flow * (1 + terminal)) / (wacc - terminal || 0.01);
  const pvTerminal = terminalValue / Math.pow(1 + wacc, 5);
  const enterpriseValue = pv + pvTerminal;
  const perShare = enterpriseValue / (shares || 1);

  $("dcf_result").innerHTML = `
    <div class="mini-stat-row"><span>PV of 5-year cash flows</span><b>Rs ${pv.toFixed(0)} mn</b></div>
    <div class="mini-stat-row"><span>PV of terminal value</span><b>Rs ${pvTerminal.toFixed(0)} mn</b></div>
    <div class="mini-stat-row"><span>Implied enterprise value</span><b>Rs ${enterpriseValue.toFixed(0)} mn</b></div>
    <div class="mini-stat-row"><span>Implied value per share</span><b class="positive">Rs ${perShare.toFixed(2)}</b></div>
  `;
}

async function calcCompareStocks() {
  const raw = $("cmp_symbols").value;
  const box = $("cmp_result");
  box.innerHTML = `<div class="loading-panel">Loading quotes…</div>`;

  try {
    const data = await getJSON(`/api/compare?symbols=${encodeURIComponent(raw)}`);

    if (!data.length) {
      box.innerHTML = `<div class="empty-chart">Enter at least one valid symbol.</div>`;
      return;
    }

    box.innerHTML = `
      <div class="table-scroll">
        <table>
          <thead><tr><th>Symbol</th><th>Company</th><th>Price</th><th>Change %</th><th>Volume</th></tr></thead>
          <tbody>
            ${data.map(x => `
              <tr>
                <td class="symbol">${esc(x.symbol)}</td>
                <td>${esc(x.company || "—")}</td>
                <td>${x.price == null ? "—" : Number(x.price).toFixed(2)}</td>
                <td class="${Number(x.change_pct||0) >= 0 ? "positive" : "negative"}">${x.change_pct == null ? "—" : Number(x.change_pct).toFixed(2)+"%"}</td>
                <td>${x.volume == null ? "—" : Number(x.volume).toLocaleString()}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  } catch (error) {
    box.innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}

function calcCompareFunds() {
  const funds = window._toolFunds || [];
  $("cmpf_result").innerHTML = `
    <div class="table-scroll">
      <table>
        <thead><tr><th>Fund</th><th>AMC</th><th>Category</th><th>NAV</th><th>YTD</th><th>AUM</th></tr></thead>
        <tbody>
          ${funds.map(f => `
            <tr>
              <td class="symbol">${esc(f.name)}</td>
              <td>${esc(f.amc || "—")}</td>
              <td>${esc(f.category || "—")}</td>
              <td>${f.nav != null ? Number(f.nav).toFixed(2) : "—"}</td>
              <td class="${f.ytd == null ? "" : (f.ytd >= 0 ? "positive" : "negative")}">
                ${f.ytd == null ? "—" : `${f.ytd >= 0 ? "+" : ""}${f.ytd}%`}
              </td>
              <td>${f.aum_mn != null ? `Rs ${(f.aum_mn / 1000).toFixed(2)}bn` : "—"}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}


/* =========================================================
   World Clock & trading sessions
   ========================================================= */

function localTimeInZone(tz) {
  return new Date(new Date().toLocaleString("en-US", { timeZone: tz }));
}

function marketStatus(market) {
  const now = localTimeInZone(market.tz);
  const day = now.getDay();
  const minutesNow = now.getHours() * 60 + now.getMinutes();

  const [oh, om] = market.open.split(":").map(Number);
  const [ch, cm] = market.close.split(":").map(Number);
  const openMinutes = oh * 60 + om;
  const closeMinutes = ch * 60 + cm;

  const isTradingDay = market.days.includes(day);
  const isOpen = isTradingDay && minutesNow >= openMinutes && minutesNow < closeMinutes;

  // Minutes until next open (search forward up to 8 days)
  let minutesToOpen = null;
  for (let d = 0; d <= 8; d++) {
    const checkDay = (day + d) % 7;
    if (!market.days.includes(checkDay)) continue;
    const dayStartMinutes = d === 0 ? minutesNow : 0;
    if (d === 0 && minutesNow >= openMinutes) continue;
    minutesToOpen = d * 24 * 60 + (openMinutes - dayStartMinutes);
    break;
  }

  let minutesToClose = null;
  if (isOpen) minutesToClose = closeMinutes - minutesNow;

  return {
    now,
    isOpen,
    minutesToOpen,
    minutesToClose,
  };
}

function fmtDuration(mins) {
  if (mins == null) return "—";
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function fmtClock(d) {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

async function loadWorldClock() {
  const d = await getJSON("/api/world-clock");

  const marketsWithStatus = d.markets.map(m => ({ ...m, status: marketStatus(m) }));
  marketsWithStatus.sort((a, b) => {
    if (a.status.isOpen !== b.status.isOpen) return a.status.isOpen ? -1 : 1;
    const at = a.status.isOpen ? a.status.minutesToClose : a.status.minutesToOpen;
    const bt = b.status.isOpen ? b.status.minutesToClose : b.status.minutesToOpen;
    return (at ?? 999999) - (bt ?? 999999);
  });

  $("worldMarketsGrid").innerHTML = marketsWithStatus.map(m => `
    <div class="card world-clock-card ${m.status.isOpen ? "market-open" : "market-closed"}">
      <div class="world-clock-head">
        <strong>${esc(m.name)}</strong>
        <span class="status-dot ${m.status.isOpen ? "dot-open" : "dot-closed"}">
          ${m.status.isOpen ? "OPEN" : "CLOSED"}
        </span>
      </div>
      <small>${esc(m.city)} · ${m.open}–${m.close} local</small>
      <div class="world-clock-time">${fmtClock(m.status.now)}</div>
      <div class="world-clock-eta">
        ${m.status.isOpen
          ? `Closes in ${fmtDuration(m.status.minutesToClose)}`
          : `Opens in ${fmtDuration(m.status.minutesToOpen)}`}
      </div>
    </div>
  `).join("");

  const sessionsWithStatus = d.forex_sessions.map(s => ({
    ...s,
    status: marketStatus({ ...s, days: [1, 2, 3, 4, 5] }),
  }));

  $("forexSessionList").innerHTML = sessionsWithStatus.map(s => `
    <div class="card world-clock-card ${s.status.isOpen ? "market-open" : "market-closed"}">
      <div class="world-clock-head">
        <strong>${esc(s.name)}</strong>
        <span class="status-dot ${s.status.isOpen ? "dot-open" : "dot-closed"}">
          ${s.status.isOpen ? "OPEN" : "CLOSED"}
        </span>
      </div>
      <small>${s.open}–${s.close} local</small>
      <div class="world-clock-time">${fmtClock(s.status.now)}</div>
      <div class="world-clock-eta">
        ${s.status.isOpen
          ? `Closes in ${fmtDuration(s.status.minutesToClose)}`
          : `Opens in ${fmtDuration(s.status.minutesToOpen)}`}
      </div>
    </div>
  `).join("");

  $("forexSessionTrack").innerHTML = `
    <div class="session-track">
      ${sessionsWithStatus.map(s => `
        <div class="session-block ${s.status.isOpen ? "session-open" : ""}">
          <span>${esc(s.name)}</span>
        </div>
      `).join("")}
    </div>
  `;
}


/* =========================================================
   Pre-market alert banner
   ========================================================= */

async function checkPremarketSignal() {
  try {
    const d = await getJSON("/api/premarket-signal");
    if (!d.alert) return;

    $("premarketTitle").textContent =
      `Overnight markets pointing lower ahead of PSX open (${d.down_count} down vs ${d.up_count} up)`;
    $("premarketDetail").textContent =
      `Down: ${d.down_markets.join(", ")}. ${d.note}`;
    $("premarketBanner").classList.remove("hidden");

    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("Yalvon360: Overnight markets pointing lower", {
        body: `${d.down_count} of the tracked global markets are down ahead of PSX open.`,
      });
    }
  } catch (error) {
    // Silently skip — this is a non-critical enhancement.
  }
}

$("premarketDismiss")?.addEventListener("click", () => {
  $("premarketBanner").classList.add("hidden");
});


/* =========================================================
   Per-holding calendar modal
   ========================================================= */

async function openHoldingCalendar(symbol) {
  const modal = $("holdingModal");
  modal.classList.remove("hidden");
  $("holdingModalSymbol").textContent = symbol;
  $("holdingModalCompany").textContent = "Loading…";
  $("holdingModalStats").innerHTML = "";
  $("holdingModalChart").innerHTML = `<div class="loading-panel">Loading…</div>`;
  $("holdingModalCalendar").innerHTML = "";
  $("holdingModalSelectedDay").innerHTML = "";

  try {
    const d = await getJSON(`/api/portfolio/holding/${encodeURIComponent(symbol)}`);
    renderHoldingModal(d);
  } catch (error) {
    $("holdingModalCompany").textContent = "";
    $("holdingModalChart").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}

function renderHoldingModal(d) {
  $("holdingModalCompany").textContent =
    `${d.company} · ${Number(d.quantity).toLocaleString()} shares @ avg ${Number(d.avg_cost).toFixed(2)} · since ${d.acquired_date || "—"}`;

  const latest = d.history.at(-1);
  const currentValue = latest ? Number(latest.value) : 0;
  const currentPnl = latest ? Number(latest.pnl) : 0;

  $("holdingModalStats").innerHTML = `
    <div class="card stat">
      <small>Current Price</small>
      <strong>${d.current_price != null ? Number(d.current_price).toFixed(2) : "—"}</strong>
    </div>
    <div class="card stat">
      <small>Current Value</small>
      <strong>${money(currentValue)}</strong>
    </div>
    <div class="card stat">
      <small>Total P/L To Date</small>
      <strong class="${currentPnl >= 0 ? "positive" : "negative"}">
        ${currentPnl >= 0 ? "+" : "-"}${money(Math.abs(currentPnl))}
      </strong>
    </div>
    <div class="card stat">
      <small>Days Tracked</small>
      <strong>${d.history.length}</strong>
    </div>
  `;

  $("holdingModalChart").innerHTML = makeSvgLine(d.history.map(h => Number(h.value)));

  if (!d.history.length) {
    $("holdingModalCalendar").innerHTML = `<div class="calendar-empty">No history yet.</div>`;
    return;
  }

  $("holdingModalCalendar").innerHTML = d.history.map((item, i) => {
    const daily = Number(item.daily_pnl_change);
    const total = Number(item.pnl);
    const day = new Date(item.day + "T00:00:00");

    return `
      <div class="calendar-day ${daily >= 0 ? "calendar-up" : "calendar-down"}" data-history-index="${i}">
        <div class="calendar-date">
          <span>${day.toLocaleDateString(undefined, {month:"short"})}${item.estimated ? ` <b class="est-tag">Est.</b>` : ""}</span>
          <strong>${day.getDate()}</strong>
        </div>
        <div class="calendar-daily">
          <small>DAY</small>
          <b>${daily >= 0 ? "+" : "-"}${money(Math.abs(daily))}</b>
        </div>
        <div class="calendar-total">
          <small>TOTAL P/L</small>
          <span class="${total >= 0 ? "positive" : "negative"}">
            (${total >= 0 ? "+" : "-"}${money(Math.abs(total))})
          </span>
        </div>
      </div>
    `;
  }).join("");

  document.querySelectorAll("#holdingModalCalendar [data-history-index]").forEach(el => {
    el.addEventListener("click", () => {
      const item = d.history[Number(el.dataset.historyIndex)];
      const day = new Date(item.day + "T00:00:00");
      const total = Number(item.pnl);

      $("holdingModalSelectedDay").innerHTML = `
        <strong>${day.toLocaleDateString(undefined, {weekday:"long", month:"long", day:"numeric", year:"numeric"})}</strong>
        <span>Cumulative P/L up to this day:</span>
        <b class="${total >= 0 ? "positive" : "negative"}">
          ${total >= 0 ? "+" : "-"}${money(Math.abs(total))}
        </b>
        ${item.estimated ? `<small class="est-tag">Estimated day</small>` : ""}
      `;
    });
  });
}

$("closeHoldingModal")?.addEventListener("click", () => {
  $("holdingModal").classList.add("hidden");
});
$("holdingModal")?.addEventListener("click", (e) => {
  if (e.target.id === "holdingModal") $("holdingModal").classList.add("hidden");
});


/* =========================================================
   Pakistan Mutual Funds (MUFAP)
   ========================================================= */

let allFunds = [];
let filteredFunds = [];
let fundsPage = 1;
const FUNDS_PER_PAGE = 50;

async function loadMutualFunds() {
  $("mutualFundsSource").textContent = "Loading…";
  $("mutualFundsTable").innerHTML = `<tr><td colspan="7"><div class="loading-panel">Loading fund directory…</div></td></tr>`;

  try {
    const d = await getJSON("/api/mutual-funds");
    allFunds = d.funds;
    renderMutualFunds(d);
  } catch (error) {
    $("mutualFundsSource").textContent = "Unable to load funds.";
    $("mutualFundsTable").innerHTML = `<tr><td colspan="7"><div class="error-panel">${esc(error.message)}</div></td></tr>`;
  }
}

function renderMutualFunds(d) {
  const isLive = d.source && d.source.startsWith("MUFAP live");
  $("mutualFundsSource").innerHTML =
    `${isLive ? "🟢 Live NAV from MUFAP" : "🟡 MUFAP directory"} · ${esc(d.source)}`;

  const query = ($("fundSearch")?.value || "").trim().toUpperCase();
  const category = $("fundCategoryFilter")?.value || "";

  filteredFunds = d.funds.filter(f => {
    const matchesQuery = !query ||
      f.name.toUpperCase().includes(query) ||
      (f.amc || "").toUpperCase().includes(query) ||
      (f.category || "").toUpperCase().includes(query);
    const matchesCategory = !category || f.category === category;
    return matchesQuery && matchesCategory;
  });

  fundsPage = 1;
  renderFundsPage();

  if ($("fundCategoryFilter") && $("fundCategoryFilter").options.length <= 1) {
    const categories = [...new Set(d.funds.map(f => f.category).filter(Boolean))].sort();
    $("fundCategoryFilter").innerHTML =
      `<option value="">All categories</option>` +
      categories.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  }
}

function renderFundsPage() {
  const totalPages = Math.max(1, Math.ceil(filteredFunds.length / FUNDS_PER_PAGE));
  fundsPage = Math.max(1, Math.min(fundsPage, totalPages));
  const start = (fundsPage - 1) * FUNDS_PER_PAGE;
  const funds = filteredFunds.slice(start, start + FUNDS_PER_PAGE);

  $("fundCount").textContent = `${filteredFunds.length.toLocaleString()} of ${allFunds.length.toLocaleString()} funds`;

  $("mutualFundsTable").innerHTML = funds.map(f => `
    <tr class="${f.ytd == null ? "" : (f.ytd >= 0 ? "tint-positive" : "tint-negative")}">
      <td>${watchStarButton(f.name, "fund", f.name, f.nav, f.ytd)}</td>
      <td class="symbol">${esc(f.name)}</td>
      <td>${esc(f.amc || "—")}</td>
      <td><span class="sector-tag">${esc(f.category || "—")}</span></td>
      <td>${f.nav != null ? Number(f.nav).toFixed(2) : "—"}</td>
      <td class="${f.ytd == null ? "" : (f.ytd >= 0 ? "positive" : "negative")}">
        ${f.ytd == null ? "—" : `${f.ytd >= 0 ? "+" : ""}${f.ytd}%`}
      </td>
      <td>${f.aum_mn != null ? `Rs ${(f.aum_mn / 1000).toFixed(2)}bn` : "—"}</td>
      <td>${esc(f.inception || "—")}</td>
      <td class="holding-sparkline">${f.trend && f.trend.length > 1 ? makeSvgLine(f.trend, f.ytd >= 0 ? "chart-line positive-line" : "chart-line negative-line") : `<span class="soft-chip" title="NAV history builds up over time as this feature runs">Building…</span>`}</td>
    </tr>
  `).join("") || `<tr><td colspan="9"><div class="empty-chart">No funds match your filters.</div></td></tr>`;

  wireWatchStarButtons($("mutualFundsTable"));

  $("fundsPageInfo").textContent = `Page ${fundsPage} of ${totalPages}`;
  $("fundsPrevPageBtn").disabled = fundsPage <= 1;
  $("fundsNextPageBtn").disabled = fundsPage >= totalPages;
}

$("fundCategoryFilter")?.addEventListener("change", () => renderMutualFunds({ funds: allFunds, source: $("mutualFundsSource").textContent }));
$("fundsPrevPageBtn")?.addEventListener("click", () => { fundsPage--; renderFundsPage(); });
$("fundsNextPageBtn")?.addEventListener("click", () => { fundsPage++; renderFundsPage(); });

$("fundSearch")?.addEventListener("input", () => renderMutualFunds({ funds: allFunds, source: $("mutualFundsSource").textContent }));

async function refreshMutualFunds() {
  const btn = $("refreshFundsBtn");
  const old = btn.textContent;

  try {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    const d = await getJSON("/api/mutual-funds/refresh", { method: "POST" });
    allFunds = d.funds;
    renderMutualFunds(d);
  } catch (error) {
    await siteAlert(error.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

$("refreshFundsBtn")?.addEventListener("click", refreshMutualFunds);


/* =========================================================
   Cryptocurrencies (CoinGecko, live, no API key)
   ========================================================= */

let allCoins = [];
let filteredCoins = [];
let cryptoPage = 1;
const CRYPTO_PER_PAGE_UI = 50;

function fmtLargeNumber(n) {
  if (n == null) return "—";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${Number(n).toLocaleString()}`;
}

async function loadCrypto() {
  $("cryptoSource").textContent = "Loading…";
  $("cryptoTable").innerHTML = `<tr><td colspan="8"><div class="loading-panel">Fetching live prices…</div></td></tr>`;

  try {
    const d = await getJSON("/api/crypto/live");
    allCoins = d.coins;
    filteredCoins = allCoins;
    cryptoPage = 1;
    renderCryptoMeta(d);
    renderCryptoPage();
    renderCryptoTopStrip();
  } catch (error) {
    $("cryptoSource").textContent = "Unable to load crypto prices.";
    $("cryptoTable").innerHTML = `<tr><td colspan="8"><div class="error-panel">${esc(error.message)}</div></td></tr>`;
  }

  loadCryptoSentiment();
}

function renderCryptoTopStrip() {
  if (!$("cryptoTopStrip")) return;
  $("cryptoTopStrip").innerHTML = allCoins.slice(0, 6).map(c => {
    const pct = c.price_change_percentage_24h || 0;
    const hasReal = c.sparkline_7d && c.sparkline_7d.length > 1;
    return `
      <div class="index-card ${pct >= 0 ? "tint-positive" : "tint-negative"}">
        <small>${esc(c.symbol)}</small>
        <strong>$${Number(c.current_price).toLocaleString(undefined,{maximumFractionDigits: c.current_price < 1 ? 4 : 2})}</strong>
        <span class="${pct >= 0 ? "positive" : "negative"}">${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%</span>
        <div class="card-sparkline">
          ${hasReal
            ? makeSvgLine(c.sparkline_7d, pct >= 0 ? "spark-line positive-line" : "spark-line negative-line")
            : seededSparkline(c.symbol, pct)}
        </div>
        ${hasReal ? `<small class="soft-chip sparkline-real-tag">7d</small>` : ""}
      </div>
    `;
  }).join("");
}

async function loadCryptoSentiment() {
  if (!$("cryptoSentimentRing")) return;
  try {
    const s = await getJSON("/api/crypto/sentiment");
    setRing("cryptoSentimentRing", "cryptoSentimentScore", "cryptoSentimentLabel", s.score, s.label);
    $("cryptoSentimentSource").textContent = s.source.startsWith("alternative.me") ? "🟢 Live · alternative.me" : "🟡 " + s.source;
    $("cryptoSentimentBar").innerHTML = `<i class="up" style="width:${s.score}%"></i>`;
  } catch (error) {
    $("cryptoSentimentSource").textContent = "Unable to load sentiment.";
  }
}

function renderCryptoMeta(d) {
  const isLive = d.source && d.source.startsWith("CoinGecko live");
  $("cryptoSource").innerHTML =
    `${isLive ? "🟢 Live from CoinGecko" : "🟡 Development data"} · ${esc(d.source)} · ${d.count} coins tracked`;
}

function applyCryptoFilter() {
  const query = ($("cryptoSearch").value || "").trim().toUpperCase();
  filteredCoins = query
    ? allCoins.filter(c => c.name.toUpperCase().includes(query) || c.symbol.toUpperCase().includes(query))
    : allCoins;
  cryptoPage = 1;
  renderCryptoPage();
}

function renderCryptoPage() {
  const totalPages = Math.max(1, Math.ceil(filteredCoins.length / CRYPTO_PER_PAGE_UI));
  cryptoPage = Math.max(1, Math.min(cryptoPage, totalPages));
  const start = (cryptoPage - 1) * CRYPTO_PER_PAGE_UI;
  const items = filteredCoins.slice(start, start + CRYPTO_PER_PAGE_UI);

  $("cryptoTable").innerHTML = items.map(c => {
    const pct = c.price_change_percentage_24h;
    return `
    <tr class="${pct == null ? "" : (pct >= 0 ? "tint-positive" : "tint-negative")}">
      <td>${watchStarButton(c.symbol, "crypto", c.name, c.current_price, pct)}</td>
      <td>${c.market_cap_rank ?? "—"}</td>
      <td class="symbol">${esc(c.name)}</td>
      <td>${esc(c.symbol)}</td>
      <td>${c.current_price != null ? "$" + Number(c.current_price).toLocaleString(undefined, {maximumFractionDigits: c.current_price < 1 ? 6 : 2}) : "—"}</td>
      <td class="${pct == null ? "" : (pct >= 0 ? "positive" : "negative")}">
        ${pct == null ? "—" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`}
      </td>
      <td>${fmtLargeNumber(c.market_cap)}</td>
      <td>${fmtLargeNumber(c.total_volume)}</td>
      <td class="holding-sparkline">${c.sparkline_7d && c.sparkline_7d.length > 1 ? makeSvgLine(c.sparkline_7d, pct >= 0 ? "chart-line positive-line" : "chart-line negative-line") : "—"}</td>
    </tr>
  `;
  }).join("") || `<tr><td colspan="9"><div class="empty-chart">No coins match your search.</div></td></tr>`;

  wireWatchStarButtons($("cryptoTable"));

  $("cryptoCount").textContent = `${filteredCoins.length.toLocaleString()} coins`;
  $("cryptoPageInfo").textContent = `Page ${cryptoPage} of ${totalPages}`;
  $("cryptoPrevPageBtn").disabled = cryptoPage <= 1;
  $("cryptoNextPageBtn").disabled = cryptoPage >= totalPages;
}

$("cryptoSearch")?.addEventListener("input", applyCryptoFilter);
$("cryptoPrevPageBtn")?.addEventListener("click", () => { cryptoPage--; renderCryptoPage(); });
$("cryptoNextPageBtn")?.addEventListener("click", () => { cryptoPage++; renderCryptoPage(); });

async function refreshCrypto() {
  const btn = $("refreshCryptoBtn");
  const old = btn.textContent;

  try {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    const d = await getJSON("/api/crypto/live/refresh", { method: "POST" });
    allCoins = d.coins;
    applyCryptoFilter();
    renderCryptoMeta(d);
  } catch (error) {
    await siteAlert(error.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

$("refreshCryptoBtn")?.addEventListener("click", refreshCrypto);


/* =========================================================
   Forex (Frankfurter / ECB, live, no API key)
   ========================================================= */

let allForexRates = {};

async function loadForex() {
  $("forexSource").textContent = "Loading…";
  $("forexTable").innerHTML = `<tr><td colspan="4"><div class="loading-panel">Fetching live rates…</div></td></tr>`;

  try {
    const d = await getJSON("/api/forex/live");
    allForexRates = d.rates;
    renderForexMeta(d);
    renderForexTable();
  } catch (error) {
    $("forexSource").textContent = "Unable to load forex rates.";
    $("forexTable").innerHTML = `<tr><td colspan="4"><div class="error-panel">${esc(error.message)}</div></td></tr>`;
  }
}

function renderForexMeta(d) {
  const isLive = d.source && d.source.startsWith("Frankfurter");
  $("forexSource").innerHTML =
    `${isLive ? "🟢 Live" : "🟡 Development data"} · ${esc(d.source)}${d.date ? " · " + esc(d.date) : ""} · base USD`;
}

function renderForexTable() {
  const query = ($("forexSearch").value || "").trim().toUpperCase();
  const entries = Object.entries(allForexRates)
    .filter(([code]) => !query || code.includes(query))
    .sort(([a], [b]) => a.localeCompare(b));

  $("forexCount").textContent = `${entries.length.toLocaleString()} currencies`;

  $("forexTable").innerHTML = entries.map(([code, rate]) => `
    <tr>
      <td>${watchStarButton(code, "forex", `USD/${code}`, rate, null)}</td>
      <td class="symbol">USD/${esc(code)}</td>
      <td>${Number(rate).toFixed(4)}</td>
      <td>1 USD = ${Number(rate).toFixed(4)} ${esc(code)}</td>
      <td>1 ${esc(code)} = $${(1 / rate).toFixed(4)}</td>
    </tr>
  `).join("") || `<tr><td colspan="5"><div class="empty-chart">No currency matches "${esc(query)}".</div></td></tr>`;

  wireWatchStarButtons($("forexTable"));
}

$("forexSearch")?.addEventListener("input", renderForexTable);

async function refreshForex() {
  const btn = $("refreshForexBtn");
  const old = btn.textContent;

  try {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    const d = await getJSON("/api/forex/live/refresh", { method: "POST" });
    allForexRates = d.rates;
    renderForexMeta(d);
    renderForexTable();
  } catch (error) {
    await siteAlert(error.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

$("refreshForexBtn")?.addEventListener("click", refreshForex);


/* =========================================================
   Commodities
   ========================================================= */

function commodityCardHtml(item) {
  const pct = Number(item.change_pct || 0);
  return `
    <div class="index-card ${pct >= 0 ? "tint-positive" : "tint-negative"}">
      <div class="multi-market-card-head">
        <small>${esc(item.name)}</small>
        <span class="data-badge ${item.source === "Development value" ? "badge-dev" : "badge-live"}">
          ${item.source === "Development value" ? "DEV" : "LIVE"}
        </span>
      </div>
      <strong>${Number(item.price).toLocaleString(undefined, {maximumFractionDigits: 2})}</strong>
      <span class="${pct >= 0 ? "positive" : "negative"}">
        ${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%
      </span>
      <div class="card-sparkline">${seededSparkline(item.key || item.name, pct)}</div>
      <div class="commodity-unit">${esc(item.unit)}</div>
    </div>
  `;
}

async function loadCommodities() {
  $("commoditiesSource").textContent = "Loading…";
  $("commoditiesGrid").innerHTML = `<div class="loading-panel">Loading…</div>`;

  try {
    const d = await getJSON("/api/commodities/live");
    $("commoditiesSource").textContent = d.live_data_enabled
      ? "Live where available (Twelve Data), development values elsewhere"
      : "Development values — set MARKET_DATA_API_KEY for live metals/energy prices";

    if (!d.live_data_enabled) $("commoditiesNotice")?.classList.remove("hidden");

    $("commoditiesGrid").innerHTML = d.commodities.map(commodityCardHtml).join("");
  } catch (error) {
    $("commoditiesSource").textContent = "Unable to load commodities.";
    $("commoditiesGrid").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  }
}


/* =========================================================
   Dashboard highlights: Major Forex / Top Funds / Commodities
   ========================================================= */

function buildTickerStrip(label, items) {
  const doubled = [...items, ...items]; // duplicate for seamless CSS loop
  return `
    <div class="ticker-strip">
      <span class="ticker-strip-label">${esc(label)}</span>
      <span class="ticker-track">
        ${doubled.map(i => `
          <span class="ticker-item">
            <b>${esc(i.symbol)}</b>
            ${i.price}
            <span class="${i.pct >= 0 ? "positive" : "negative"}">${i.pct >= 0 ? "▲" : "▼"}${Math.abs(i.pct).toFixed(2)}%</span>
          </span>
        `).join("")}
      </span>
    </div>
  `;
}

async function loadDashboardTickers() {
  if (!$("globalTickerBar")) return;

  try {
    const [stocks, crypto, forex, funds] = await Promise.all([
      getJSON("/api/stocks/live").catch(() => ({ items: [] })),
      getJSON("/api/crypto/live").catch(() => ({ coins: [] })),
      getJSON("/api/forex/live").catch(() => ({ rates: {} })),
      getJSON("/api/mutual-funds").catch(() => ({ funds: [] })),
    ]);

    const psxItems = stocks.items.filter(s => s.price != null).slice(0, 15)
      .map(s => ({ symbol: s.symbol, price: Number(s.price).toFixed(2), pct: Number(s.change_pct || 0) }));

    const cryptoItems = crypto.coins.slice(0, 15)
      .map(c => ({ symbol: c.symbol, price: "$" + Number(c.current_price).toLocaleString(undefined, {maximumFractionDigits: c.current_price < 1 ? 4 : 2}), pct: Number(c.price_change_percentage_24h || 0) }));

    const forexItems = Object.entries(forex.rates).slice(0, 15)
      .map(([code, rate]) => ({ symbol: `USD/${code}`, price: Number(rate).toFixed(3), pct: 0 }));

    const fundItems = funds.funds.filter(f => f.nav != null).slice(0, 15)
      .map(f => ({ symbol: f.name.slice(0, 22), price: Number(f.nav).toFixed(2), pct: Number(f.ytd || 0) }));

    $("globalTickerBar").innerHTML = [
      psxItems.length ? buildTickerStrip("PSX LIVE", psxItems) : "",
      cryptoItems.length ? buildTickerStrip("CRYPTO LIVE", cryptoItems) : "",
      forexItems.length ? buildTickerStrip("FOREX LIVE", forexItems) : "",
      fundItems.length ? buildTickerStrip("MUTUAL FUNDS", fundItems) : "",
    ].join("");
  } catch (error) {
    // Ticker strips are a non-critical enhancement.
  }
}

async function loadDashboardHighlights() {
  try {
    const d = await getJSON("/api/dashboard-highlights");

    if ($("dashForexStrip")) {
      $("dashForexSource").textContent = d.forex_source?.startsWith("Frankfurter") ? "🟢 Live" : "🟡 Development data";
      $("dashForexStrip").innerHTML = d.major_forex.map(f => `
        <div class="mini-stat-row">
          <span>USD/${esc(f.code)}</span>
          <b>${Number(f.rate).toFixed(2)}</b>
        </div>
      `).join("") || `<div class="empty-chart">Unavailable</div>`;
    }

    if ($("dashFundsStrip")) {
      $("dashFundsStrip").innerHTML = d.top_funds.map(f => `
        <div class="mini-stat-row">
          <span>${esc(f.name)}</span>
          <b>${f.aum_mn != null ? `Rs ${(f.aum_mn / 1000).toFixed(1)}bn` : "—"}</b>
        </div>
      `).join("") || `<div class="empty-chart">Unavailable</div>`;
    }

    if ($("dashCommoditiesStrip")) {
      $("dashCommoditiesStrip").innerHTML = d.commodities.slice(0, 5).map(c => `
        <div class="mini-stat-row">
          <span>${esc(c.name)}</span>
          <b class="${c.change_pct >= 0 ? "positive" : "negative"}">
            ${Number(c.price).toLocaleString(undefined,{maximumFractionDigits:2})}
            <small>${c.change_pct >= 0 ? "▲" : "▼"} ${Math.abs(c.change_pct).toFixed(2)}%</small>
          </b>
        </div>
      `).join("") || `<div class="empty-chart">Unavailable</div>`;
    }
  } catch (error) {
    // Non-critical dashboard enhancement — fail silently.
  }
}

/* =========================================================
   Stock Screener
   ========================================================= */

let screenerCatalogLoaded = false;

const SCREENER_PRESETS = [
  { label: "🟢 Oversold (RSI ≤ 30)", criteria: { rsi_oversold: true } },
  { label: "🔴 Overbought (RSI ≥ 70)", criteria: { rsi_overbought: true } },
  { label: "📈 Bullish Trend (Golden Cross)", criteria: { golden_cross: true } },
  { label: "📉 Bearish Trend (Death Cross)", criteria: { death_cross: true } },
  { label: "🚀 MACD Bullish", criteria: { macd_bullish: true } },
  { label: "💹 Above 200-day Average", criteria: { above_sma200: true } },
  { label: "🔥 High Volume", criteria: { volume_min: 5000000 } },
  { label: "💰 Value (P/E under 10)", criteria: { pe_max: 10 } },
  { label: "⬆️ Big Gainers Today (≥5%)", criteria: { change_pct_min: 5 } },
  { label: "⬇️ Big Losers Today (≤-5%)", criteria: { change_pct_max: -5 } },
  { label: "🏔️ Near 52-Week High", criteria: { week52_position: "near_high" } },
  { label: "🕳️ Near 52-Week Low", criteria: { week52_position: "near_low" } },
];

function renderScreenerPresets() {
  if (!$("screenerPresets")) return;
  $("screenerPresets").innerHTML = SCREENER_PRESETS.map((p, i) => `
    <button class="screener-preset-btn" data-preset-idx="${i}">${p.label}</button>
  `).join("") + `<p class="muted-note screener-preset-note">Presets scan PSX stocks only right now — crypto/forex/commodity screening needs those markets' own indicator history first.</p>`;

  document.querySelectorAll("[data-preset-idx]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".screener-preset-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      runScreener(SCREENER_PRESETS[Number(btn.dataset.presetIdx)].criteria);
    });
  });
}

async function loadScreener() {
  if (!screenerCatalogLoaded) {
    await loadScreenerCatalog();
    screenerCatalogLoaded = true;
  }
  populateScreenerSectors();
  renderScreenerPresets();
}

function populateScreenerSectors() {
  const select = $("f_sector");
  if (!select || select.dataset.populated) return;

  const sectors = [...new Set(allSymbols.map(x => x.sector).filter(Boolean))].sort();
  select.innerHTML =
    `<option value="">All sectors</option>` +
    sectors.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  select.dataset.populated = "1";
}

async function loadScreenerCatalog() {
  const d = await getJSON("/api/screener/catalog");

  if (d.recording_progress) {
    const p = d.recording_progress;
    const banner = $("screenerRecordingBanner");
    if (banner) {
      banner.innerHTML = p.days_recorded > 0
        ? `📈 <b>${p.days_recorded}</b> trading day${p.days_recorded === 1 ? "" : "s"} of price history recorded since ${esc(p.started_on)}. Indicators below activate automatically as more history builds up — no action needed.`
        : `📈 Technical-indicator history starts recording the moment your first live price refresh runs. Indicators below will switch from "Activating" to fully live automatically — no action needed.`;
    }
  }

  $("screenerCatalog").innerHTML = d.sections
    .filter(section => section.section !== "Today's Trading (available now)")
    .map(section => `
      <div class="card screener-section-card">
        <div class="card-head"><h3>${esc(section.section)}</h3></div>
        <div class="screener-checklist">
          ${section.items.map(item => {
            const isActivating = item.available && item.activating;
            const isLive = item.available && !item.activating;
            const badge = isLive
              ? `<span class="data-badge badge-live">LIVE</span>`
              : isActivating
                ? `<span class="data-badge badge-activating">ACTIVATING</span>`
                : `<span class="data-badge badge-dev">SOON</span>`;
            const cls = isLive ? "checklist-live" : (isActivating ? "checklist-activating" : "checklist-disabled");
            const title = isLive ? "Live filter — check it, then Run Screener" : esc(item.reason || "Not available yet");
            const fk = item.filter_key || "";

            return `
              <label class="checklist-item ${cls}" title="${title}">
                <input type="checkbox" data-filter-key="${esc(fk)}" ${isLive ? "" : "disabled"}>
                <span>${esc(item.label)}</span>
                ${badge}
              </label>
              ${isActivating ? `<div class="checklist-progress-note">${esc(item.reason)}</div>` : ""}
            `;
          }).join("")}
        </div>
      </div>
    `).join("");
}

const CHECKLIST_FILTER_KEY_MAP = {
  ema20: { above_sma20: true },
  sma50: { above_sma50: true },
  sma200: { above_sma200: true },
  golden_cross: { golden_cross: true },
  death_cross: { death_cross: true },
  macd: { macd_bullish: true },
  volume_confirmation: { volume_min: 5000000 },
};

function collectScreenerCriteria() {
  const criteria = {};
  const num = id => {
    const v = $(id).value;
    return v === "" ? null : Number(v);
  };

  criteria.price_min = num("f_price_min");
  criteria.price_max = num("f_price_max");
  criteria.change_pct_min = num("f_change_min");
  criteria.change_pct_max = num("f_change_max");
  criteria.pe_min = num("f_pe_min");
  criteria.pe_max = num("f_pe_max");
  criteria.one_year_change_min = num("f_1y_min");
  criteria.ytd_change_min = num("f_ytd_min");
  criteria.volume_min = num("f_volume_min");

  const week52 = $("f_week52_position").value;
  if (week52) criteria.week52_position = week52;

  const sector = $("f_sector").value;
  if (sector) criteria.sectors = [sector];

  if ($("f_above_ldcp").checked) criteria.above_ldcp = true;

  document.querySelectorAll('[data-filter-key]:checked').forEach(box => {
    const extra = CHECKLIST_FILTER_KEY_MAP[box.dataset.filterKey];
    if (extra) Object.assign(criteria, extra);
  });

  return criteria;
}

function renderActiveFilterChips(criteria) {
  const labels = {
    price_min: v => `Price ≥ ${v}`, price_max: v => `Price ≤ ${v}`,
    change_pct_min: v => `Change % ≥ ${v}`, change_pct_max: v => `Change % ≤ ${v}`,
    pe_min: v => `P/E ≥ ${v}`, pe_max: v => `P/E ≤ ${v}`,
    one_year_change_min: v => `1Y Change ≥ ${v}%`, ytd_change_min: v => `YTD Change ≥ ${v}%`,
    volume_min: v => `Volume ≥ ${Number(v).toLocaleString()}`,
    week52_position: v => `52-week position: ${v.replace("_"," ")}`,
    sectors: v => `Sector: ${v.join(", ")}`,
    above_ldcp: () => `Above yesterday's close`,
  };

  const chips = Object.entries(criteria)
    .filter(([, v]) => v !== null && v !== undefined && v !== false)
    .map(([k, v]) => labels[k] ? labels[k](v) : null)
    .filter(Boolean);

  $("activeFilterChips").innerHTML = chips.length
    ? chips.map(c => `<span class="filter-chip">${esc(c)}</span>`).join("")
    : `<span class="muted-note">No filters yet — add some above, then press Run Screener.</span>`;
}

async function runScreener(presetCriteria = null) {
  const criteria = presetCriteria || collectScreenerCriteria();
  renderActiveFilterChips(criteria);

  const btn = $("runScreenerBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Scanning…";
  $("screenerResults").innerHTML = `<div class="loading-panel">Scanning PSX symbols against your filters…</div>`;

  try {
    const response = await fetch("/api/screener/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(criteria),
    });
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const d = await response.json();

    $("screenerResultCount").textContent = `${d.count} match${d.count === 1 ? "" : "es"} of ${d.scanned} scanned`;

    $("screenerResults").innerHTML = d.results.length
      ? `
        <table>
          <thead>
            <tr><th>Symbol</th><th>Company</th><th>Sector</th><th>Price</th><th>Change %</th><th>P/E</th><th>Volume</th></tr>
          </thead>
          <tbody>
            ${d.results.map(r => `
              <tr class="clickable-row" data-symbol-open="${esc(r.symbol)}">
                <td class="symbol">${esc(r.symbol)}</td>
                <td>${esc(r.company || "—")}</td>
                <td>${esc(r.sector || "—")}</td>
                <td>${r.price == null ? "—" : Number(r.price).toFixed(2)}</td>
                <td class="${r.change_pct == null ? "" : (r.change_pct >= 0 ? "positive" : "negative")}">
                  ${r.change_pct == null ? "—" : `${r.change_pct >= 0 ? "+" : ""}${Number(r.change_pct).toFixed(2)}%`}
                </td>
                <td>${r.pe_ratio == null ? "—" : Number(r.pe_ratio).toFixed(2)}</td>
                <td>${r.volume == null ? "—" : Number(r.volume).toLocaleString()}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `
      : `<div class="empty-chart">No stocks matched these filters.</div>`;

    document.querySelectorAll("[data-symbol-open]").forEach(el => {
      el.addEventListener("click", () => openStock(el.dataset.symbolOpen));
    });
  } catch (error) {
    $("screenerResults").innerHTML = `<div class="error-panel">${esc(error.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

$("runScreenerBtn")?.addEventListener("click", runScreener);

$("clearScreenerBtn")?.addEventListener("click", () => {
  ["f_price_min","f_price_max","f_change_min","f_change_max","f_pe_min","f_pe_max",
   "f_1y_min","f_ytd_min","f_volume_min"].forEach(id => { $(id).value = ""; });
  $("f_week52_position").value = "";
  $("f_sector").value = "";
  $("f_above_ldcp").checked = false;
  renderActiveFilterChips({});
  $("screenerResults").innerHTML = `<div class="empty-chart">Set your filters above and press Run Screener.</div>`;
  $("screenerResultCount").textContent = "";
});

checkPremarketSignal();

// =====================================================================
// Crypto Technicals / Forex Technicals (merged in from the PSX Toolkit)
// =====================================================================

const TECH_COLS = [
  { key: "display", label: "Symbol" },
  { key: "latest_close", label: "Last Price", fmt: "num" },
  { key: "latest_rsi", label: "RSI (14)" },
  { key: "structure", label: "Trend Structure" },
  { key: "bullish_divergence", label: "Bullish Divergence", fmt: "div" },
  { key: "bearish_divergence", label: "Bearish Divergence", fmt: "div" },
  { key: "latest_bar_time", label: "As Of" },
];

function fmtAgo(isoString) {
  if (!isoString) return "unknown time";
  const then = new Date(isoString);
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return then.toLocaleString();
}

function renderTechTable(rows) {
  const okRows = (rows || []).filter(r => !r.error);
  const errRows = (rows || []).filter(r => r.error);
  let html = "";

  if (okRows.length) {
    html += `<div class="tech-scan-table-wrap"><table><thead><tr>`;
    html += TECH_COLS.map(c => `<th>${c.label}</th>`).join("");
    html += `</tr></thead><tbody>`;
    for (const r of okRows) {
      html += "<tr>" + TECH_COLS.map(c => {
        let val = r[c.key];
        if (c.fmt === "div") {
          val = val
            ? `<span class="tech-tag tech-tag-yes">Yes</span> <small>${esc(val.pivot1_date || "")} → ${esc(val.pivot2_date || "")}</small>`
            : `<span class="tech-tag tech-tag-no">No</span>`;
        } else if (c.fmt === "num" && typeof val === "number") {
          val = val.toFixed(5);
        } else if (val === null || val === undefined) {
          val = "—";
        } else {
          val = esc(String(val));
        }
        return `<td>${val}</td>`;
      }).join("") + "</tr>";
    }
    html += "</tbody></table></div>";
  } else {
    html += `<div class="empty-chart">No usable results for this timeframe yet.</div>`;
  }

  if (errRows.length) {
    html += `<p class="muted-note">Could not analyze: ${errRows.map(r => `${esc(r.display)} (${esc(r.error)})`).join("; ")}</p>`;
  }
  return html;
}

function renderIntradayTechResults(result, resultsEl, timeframeOrder) {
  let html = "";
  for (const tf of timeframeOrder) {
    html += `<div class="tech-scan-block"><h3>${esc(tf)} Timeframe</h3>${renderTechTable(result[tf])}</div>`;
  }
  resultsEl.innerHTML = html || `<div class="empty-chart">No results.</div>`;
}

async function runIntradayTechScan(startUrl, statusElId, resultsElId, timeframeOrder, runBtnId) {
  const statusEl = $(statusElId);
  const resultsEl = $(resultsElId);
  const runBtn = $(runBtnId);
  if (runBtn) runBtn.disabled = true;
  statusEl.textContent = "Starting scan…";
  try {
    const startData = await getJSON(startUrl);
    if (!startData.ok) { statusEl.textContent = "Error: " + startData.error; return; }

    while (true) {
      const data = await getJSON(startUrl.replace("/start", "/status/") + startData.job_id);
      if (!data.ok || data.status === "error") {
        statusEl.textContent = "Error: " + (data.error || "scan failed");
        return;
      }
      if (data.status === "done") {
        renderIntradayTechResults(data.result, resultsEl, timeframeOrder);
        statusEl.textContent = "Scan complete — just now.";
        return;
      }
      const p = data.progress;
      statusEl.textContent = p ? `Scanning… ${p.done}/${p.total} (${p.symbol})` : "Scanning…";
      await new Promise(r => setTimeout(r, 1500));
    }
  } catch (e) {
    statusEl.textContent = "Request failed: " + e.message;
  } finally {
    if (runBtn) runBtn.disabled = false;
  }
}

async function loadForexTechCached() {
  const statusEl = $("forexTechStatus");
  const resultsEl = $("forexTechResults");
  if (resultsEl.innerHTML.trim()) return; // already showing something this session
  try {
    const data = await getJSON("/api/forextech/scan/cached");
    if (data.ok && data.found) {
      renderIntradayTechResults(data.result, resultsEl, ["30m", "1h"]);
      statusEl.textContent = `Showing last scan from ${fmtAgo(data.saved_at)}. Press "Run Scan" to refresh.`;
    } else {
      statusEl.textContent = `No scan yet — press "Run Scan" to check forex &amp; metals for RSI divergence.`;
    }
  } catch (e) { /* silent on first load */ }
}

async function loadCryptoTechCached() {
  const statusEl = $("cryptoTechStatus");
  const resultsEl = $("cryptoTechResults");
  if (resultsEl.innerHTML.trim()) return;
  try {
    const data = await getJSON("/api/cryptotech/scan/cached");
    if (data.ok && data.found) {
      renderIntradayTechResults(data.result, resultsEl, ["30m", "1h", "4h"]);
      statusEl.textContent = `Showing last scan from ${fmtAgo(data.saved_at)}. Press "Run Scan" to refresh.`;
    } else {
      statusEl.textContent = `No scan yet — press "Run Scan" to check the top cryptocurrencies for RSI divergence.`;
    }
  } catch (e) { /* silent on first load */ }
}

$("forexTechRunBtn")?.addEventListener("click", () => {
  runIntradayTechScan("/api/forextech/scan/start", "forexTechStatus", "forexTechResults", ["30m", "1h"], "forexTechRunBtn");
});
$("cryptoTechRunBtn")?.addEventListener("click", () => {
  runIntradayTechScan("/api/cryptotech/scan/start", "cryptoTechStatus", "cryptoTechResults", ["30m", "1h", "4h"], "cryptoTechRunBtn");
});

// =====================================================================
// Portfolio CSV Import / Export (merged in from the PSX Toolkit)
// =====================================================================

$("exportPortfolioBtn")?.addEventListener("click", () => {
  window.location.href = "/api/portfolio/export";
});

$("importPortfolioBtn")?.addEventListener("click", () => {
  $("importPortfolioFile")?.click();
});

$("importPortfolioFile")?.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const statusEl = $("importPortfolioStatus");
  statusEl.textContent = "Importing…";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/portfolio/import", { method: "POST", body: formData });
    const data = await res.json();
    if (!data.ok) {
      statusEl.textContent = "Import failed: " + (data.error || "unknown error");
      return;
    }
    let msg = `Imported: ${data.added} added, ${data.updated} updated.`;
    if (data.skipped && data.skipped.length) {
      msg += ` ${data.skipped.length} row(s) skipped (bad data).`;
    }
    statusEl.textContent = msg;
    await loadPortfolio();
  } catch (err) {
    statusEl.textContent = "Import failed: " + err.message;
  } finally {
    e.target.value = "";
  }
});

// =====================================================================
// PSX Divergence Screener (merged in from the PSX Toolkit's psx_screener.py)
// =====================================================================

const PSX_DIV_COLS = [
  { key: "symbol", label: "Symbol" },
  { key: "latest_close", label: "Last Close", fmt: "num2" },
  { key: "week52_low", label: "52W Low", fmt: "num2" },
  { key: "pct_above_52w_low", label: "% Above 52W Low", fmt: "pct" },
  { key: "latest_rsi", label: "RSI (14)" },
  { key: "div_1d", label: "1D Divergence" },
  { key: "div_1w", label: "1W Divergence" },
  { key: "div_1m", label: "1M Divergence" },
  { key: "divergence_type", label: "Type" },
  { key: "pivot1_date", label: "Pivot 1" },
  { key: "pivot2_date", label: "Pivot 2" },
];

function renderPsxDivTable(rows, cols) {
  if (!rows || !rows.length) {
    return `<div class="empty-chart">No matches in this list.</div>`;
  }
  const useCols = cols || PSX_DIV_COLS.filter(c => rows.some(r => r[c.key] !== undefined));
  let html = `<div class="tech-scan-table-wrap"><table><thead><tr>`;
  html += useCols.map(c => `<th>${c.label}</th>`).join("");
  html += `</tr></thead><tbody>`;
  for (const r of rows) {
    html += "<tr>" + useCols.map(c => {
      let val = r[c.key];
      if (val === null || val === undefined) val = "—";
      else if (c.fmt === "num2" && typeof val === "number") val = val.toFixed(2);
      else if (c.fmt === "pct" && typeof val === "number") val = `${val.toFixed(2)}%`;
      else val = esc(String(val));
      return `<td>${val}</td>`;
    }).join("") + "</tr>";
  }
  html += "</tbody></table></div>";
  return html;
}

function renderPsxDivergenceResult(result, resultsEl) {
  const sections = [
    ["near_low_bullish_divergence", "Near 52-Week Low + Bullish RSI Divergence", "Price near its 52-week low, with RSI making a higher low while price made a lower low — a possible sign of fading downside momentum right where it matters most."],
    ["near_low", "All Stocks Near Their 52-Week Low", "Every screened stock within a few percent of its 52-week low (not all of these show divergence)."],
    ["bullish_divergence_all", "All Bullish RSI Divergence (market-wide)", "Every stock showing a bullish divergence anywhere in the market, regardless of where it sits relative to its 52-week low."],
    ["bearish_divergence_all", "All Bearish RSI Divergence (market-wide)", "The mirror image: price made a higher high while RSI made a lower high — a possible sign of fading upside momentum."],
    ["uptrend_divergence", "Divergence Within an Uptrend Structure", "Higher-high + higher-low swing structure, also showing a divergence — see the Type column."],
    ["downtrend_divergence", "Divergence Within a Downtrend Structure", "Lower-high + lower-low swing structure, also showing a divergence — see the Type column."],
  ];

  let html = "";
  for (const [key, title, desc] of sections) {
    html += `<div class="tech-scan-block"><h3>${esc(title)}</h3><p class="muted-note">${esc(desc)}</p>${renderPsxDivTable(result[key])}</div>`;
  }
  if (result.errors && result.errors.length) {
    html += `<p class="muted-note">${result.errors.length} symbol(s) failed to download and were skipped.</p>`;
  }
  resultsEl.innerHTML = html;
}

async function runPsxDivergenceScan() {
  const statusEl = $("psxDivergenceStatus");
  const resultsEl = $("psxDivergenceResults");
  const runBtn = $("psxDivergenceRunBtn");
  if (runBtn) runBtn.disabled = true;
  statusEl.textContent = "Starting market-wide scan…";
  try {
    const startData = await getJSON("/api/psxdivergence/scan/start");
    if (!startData.ok) { statusEl.textContent = "Error: " + startData.error; return; }

    while (true) {
      const data = await getJSON("/api/psxdivergence/scan/status/" + startData.job_id);
      if (!data.ok || data.status === "error") {
        statusEl.textContent = "Error: " + (data.error || "scan failed");
        return;
      }
      if (data.status === "done") {
        renderPsxDivergenceResult(data.result, resultsEl);
        statusEl.textContent = `Scan complete — ${data.result.symbols_scanned} symbols checked, just now.`;
        return;
      }
      const p = data.progress;
      statusEl.textContent = p ? `Scanning… ${p.done}/${p.total} (${p.symbol})` : "Scanning…";
      await new Promise(r => setTimeout(r, 2000));
    }
  } catch (e) {
    statusEl.textContent = "Request failed: " + e.message;
  } finally {
    if (runBtn) runBtn.disabled = false;
  }
}

async function loadPsxDivergenceCached() {
  const statusEl = $("psxDivergenceStatus");
  const resultsEl = $("psxDivergenceResults");
  if (resultsEl.innerHTML.trim()) return;
  try {
    const data = await getJSON("/api/psxdivergence/scan/cached");
    if (data.ok && data.found) {
      renderPsxDivergenceResult(data.result, resultsEl);
      statusEl.textContent = `Showing last scan from ${fmtAgo(data.saved_at)}. Press "Run Scan" to refresh.`;
    } else {
      statusEl.textContent = `No scan yet — press "Run Scan" to check the whole PSX market for divergence and 52-week lows.`;
    }
  } catch (e) { /* silent on first load */ }
}

$("psxDivergenceRunBtn")?.addEventListener("click", runPsxDivergenceScan);

// =====================================================================
// Keep the top ticker bar (PSX / Crypto / Forex / Funds) fresh.
// It's populated once on load, but the PSX strip in particular can be
// empty on that very first call if the server's bulk PSX quote cache is
// still warming up (common right after a Render free-tier cold start).
// Re-running it periodically means the PSX line appears as soon as
// quotes are ready, instead of never appearing until a manual refresh.
// =====================================================================
setInterval(() => { loadDashboardTickers(); }, 60000);
