document.addEventListener("DOMContentLoaded", () => {
    const state = {
        period: 180,
        refreshMs: 30000,
        timer: null,
    };

    const refs = {
        statusPill: document.getElementById("status-pill"),
        connectionStatus: document.getElementById("connection-status"),
        lastSync: document.getElementById("last-sync"),
        refreshBtn: document.getElementById("refresh-btn"),
        periodButtons: Array.from(document.querySelectorAll(".period-btn")),
        totalPnl: document.getElementById("total-pnl"),
        winRate: document.getElementById("win-rate"),
        totalTrades: document.getElementById("total-trades"),
        activePositions: document.getElementById("active-positions"),
        profitFactor: document.getElementById("profit-factor"),
        maxDrawdown: document.getElementById("max-drawdown"),
        riskStatus: document.getElementById("risk-status"),
        netExposure: document.getElementById("net-exposure"),
        alertsCount: document.getElementById("alerts-count"),
        cumulativeTitle: document.getElementById("cumulative-title"),
        cumulativeTag: document.getElementById("cumulative-tag"),
        periodCaption: document.getElementById("period-caption"),
        recentTradesList: document.getElementById("recent-trades-list"),
        positionsList: document.getElementById("positions-list"),
        winsCount: document.getElementById("wins-count"),
        lossesCount: document.getElementById("losses-count"),
        errorBox: document.getElementById("error-box"),
    };

    const plotConfig = {
        displayModeBar: false,
        responsive: true,
    };

    function safeNumber(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function formatCurrency(value) {
        return new Intl.NumberFormat("fr-FR", {
            style: "currency",
            currency: "USD",
            minimumFractionDigits: 2,
        }).format(safeNumber(value));
    }

    function formatSignedCurrency(value) {
        const amount = safeNumber(value);
        const absolute = formatCurrency(Math.abs(amount));
        if (amount > 0) return `+${absolute}`;
        if (amount < 0) return `-${absolute}`;
        return absolute;
    }

    function formatToTimeLabel(isoString) {
        const date = new Date(isoString);
        if (Number.isNaN(date.getTime())) return "--:--";
        return date.toLocaleTimeString("fr-FR", {
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    function showError(message) {
        refs.errorBox.textContent = message;
        refs.errorBox.classList.remove("hidden");
    }

    function hideError() {
        refs.errorBox.textContent = "";
        refs.errorBox.classList.add("hidden");
    }

    function setStatus(mode, text) {
        refs.connectionStatus.textContent = text;
        refs.statusPill.classList.remove("status-pill--success", "status-pill--error", "status-pill--muted");

        if (mode === "success") {
            refs.statusPill.classList.add("status-pill--success");
            return;
        }
        if (mode === "error") {
            refs.statusPill.classList.add("status-pill--error");
            return;
        }
        refs.statusPill.classList.add("status-pill--muted");
    }

    function setActivePeriodButton() {
        refs.periodButtons.forEach((button) => {
            const buttonPeriod = Number(button.dataset.period);
            button.classList.toggle("active", buttonPeriod === state.period);
        });
    }

    function updateHeader(generatedAt) {
        const syncDate = new Date(generatedAt);
        if (Number.isNaN(syncDate.getTime())) {
            refs.lastSync.textContent = "--:--:--";
            return;
        }

        refs.lastSync.textContent = syncDate.toLocaleTimeString("fr-FR", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
    }

    function updateKpiValue(element, value, mode = "neutral") {
        element.textContent = value;
        element.classList.remove("positive", "negative", "neutral");
        element.classList.add(mode);
    }

    function updateMetrics(metrics) {
        const totalPnl = safeNumber(metrics.total_pnl);
        updateKpiValue(refs.totalPnl, formatCurrency(totalPnl), totalPnl >= 0 ? "positive" : "negative");

        const winRate = safeNumber(metrics.win_rate);
        updateKpiValue(refs.winRate, `${winRate.toFixed(1)}%`, winRate >= 50 ? "positive" : "negative");

        updateKpiValue(refs.totalTrades, String(metrics.total_trades ?? 0));
        updateKpiValue(refs.activePositions, String(metrics.active_positions ?? 0));

        const profitFactor = metrics.profit_factor === "inf" ? "inf" : safeNumber(metrics.profit_factor).toFixed(2);
        updateKpiValue(refs.profitFactor, profitFactor);

        const maxDrawdown = safeNumber(metrics.max_drawdown);
        updateKpiValue(refs.maxDrawdown, formatCurrency(maxDrawdown), maxDrawdown <= 0 ? "negative" : "positive");

        refs.cumulativeTag.textContent = formatSignedCurrency(totalPnl);
        refs.cumulativeTag.classList.remove("badge-positive", "badge-negative");
        refs.cumulativeTag.classList.add(totalPnl >= 0 ? "badge-positive" : "badge-negative");
    }

    function updateRiskBand(metrics) {
        refs.riskStatus.textContent = metrics.risk_status || "Stable";

        const openPnl = safeNumber(metrics.open_positions_pnl);
        const netVolume = safeNumber(metrics.net_position_volume);
        let direction = "flat";
        if (netVolume > 0.01) direction = "long";
        if (netVolume < -0.01) direction = "short";
        refs.netExposure.textContent = `${formatSignedCurrency(openPnl)} ${direction}`;

        const alertsCount = Number(metrics.alerts_count || 0);
        refs.alertsCount.textContent = alertsCount > 0 ? `${alertsCount} a surveiller` : "Aucune";
    }

    function renderCumulativeChart(chart) {
        Plotly.react("cumulative-pnl-chart", chart.data || [], chart.layout || {}, plotConfig);
    }

    function renderDailyChart(chart) {
        Plotly.react("daily-pnl-chart", chart.data || [], chart.layout || {}, plotConfig);
    }

    function renderSymbolChart(chart) {
        Plotly.react("symbol-pnl-chart", chart.data || [], chart.layout || {}, plotConfig);
    }

    function renderWinRateChart(chart, metrics) {
        const winRate = `${safeNumber(metrics.win_rate).toFixed(1)}%`;
        const layout = {
            ...(chart.layout || {}),
            annotations: [
                {
                    text: winRate,
                    font: {
                        family: "Manrope, sans-serif",
                        size: 16,
                        color: "#10203A",
                    },
                    showarrow: false,
                },
            ],
        };
        Plotly.react("win-rate-chart", chart.data || [], layout, plotConfig);
    }

    function renderCharts(charts, metrics) {
        renderCumulativeChart(charts.cumulative_pnl || {});
        renderDailyChart(charts.daily_pnl || {});
        renderSymbolChart(charts.symbol_pnl || {});
        renderWinRateChart(charts.win_rate || {}, metrics);
    }

    function renderTrades(deals) {
        const sortedDeals = [...(deals || [])]
            .filter((deal) => deal.time)
            .sort((a, b) => new Date(b.time) - new Date(a.time))
            .slice(0, 10);

        refs.recentTradesList.innerHTML = "";

        if (!sortedDeals.length) {
            refs.recentTradesList.innerHTML = "<div class=\"empty-row\">Aucun trade sur la periode selectionnee.</div>";
            return;
        }

        sortedDeals.forEach((trade) => {
            const row = document.createElement("div");
            row.className = "trade-row";

            const left = document.createElement("span");
            left.className = "trade-left";
            const volume = safeNumber(trade.volume).toFixed(2);
            left.textContent = `${formatToTimeLabel(trade.time)} | ${trade.symbol || "N/A"} | ${trade.type || "OTHER"} ${volume}`;

            const right = document.createElement("span");
            const pnl = safeNumber(trade.profit);
            right.className = `trade-right ${pnl >= 0 ? "positive" : "negative"}`;
            right.textContent = formatSignedCurrency(pnl);

            row.appendChild(left);
            row.appendChild(right);
            refs.recentTradesList.appendChild(row);
        });
    }

    function renderPositions(positions) {
        const sortedPositions = [...(positions || [])]
            .sort((a, b) => Math.abs(safeNumber(b.profit)) - Math.abs(safeNumber(a.profit)))
            .slice(0, 3);

        refs.positionsList.innerHTML = "";

        if (!sortedPositions.length) {
            refs.positionsList.innerHTML = "<div class=\"empty-row\">Aucune position ouverte.</div>";
            return;
        }

        sortedPositions.forEach((position) => {
            const row = document.createElement("div");
            row.className = "position-row";

            const left = document.createElement("span");
            left.className = "position-left";
            const volume = safeNumber(position.volume).toFixed(2);
            left.textContent = `${position.symbol || "N/A"} ${position.type || "OTHER"} ${volume}`;

            const right = document.createElement("span");
            const pnl = safeNumber(position.profit);
            right.className = `position-right ${pnl >= 0 ? "positive" : "negative"}`;
            right.textContent = formatSignedCurrency(pnl);

            row.appendChild(left);
            row.appendChild(right);
            refs.positionsList.appendChild(row);
        });
    }

    function updateWinLossSummary(metrics) {
        refs.winsCount.textContent = `${metrics.profitable_trades || 0} gagnants`;
        refs.lossesCount.textContent = `${metrics.losing_trades || 0} perdants`;
    }

    async function loadDashboardData() {
        try {
            setStatus("loading", "Connexion...");
            hideError();

            const response = await fetch(`/api/dashboard?period=${state.period}`, { cache: "no-store" });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const payload = await response.json();
            const metrics = payload.metrics || {};
            const charts = payload.charts || {};
            const history = payload.history || {};

            refs.cumulativeTitle.textContent = `PnL Cumulatif (${state.period} jours)`;
            refs.periodCaption.textContent = String(state.period);
            updateHeader(payload.generated_at);
            updateMetrics(metrics);
            updateRiskBand(metrics);
            renderCharts(charts, metrics);
            renderTrades(history.deals || []);
            renderPositions(history.positions || []);
            updateWinLossSummary(metrics);

            setStatus("success", "MT5 Connecte");
        } catch (error) {
            console.error("Dashboard load error:", error);
            setStatus("error", "Erreur de connexion");
            showError("Impossible de charger les donnees du dashboard. Verifie le serveur Flask et MT5.");
        }
    }

    refs.periodButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const nextPeriod = Number(button.dataset.period);
            if (!nextPeriod || nextPeriod === state.period) return;
            state.period = nextPeriod;
            setActivePeriodButton();
            loadDashboardData();
        });
    });

    refs.refreshBtn.addEventListener("click", () => {
        loadDashboardData();
    });

    setActivePeriodButton();
    loadDashboardData();
    state.timer = setInterval(loadDashboardData, state.refreshMs);
});
