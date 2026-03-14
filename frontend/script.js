// Script pour le dashboard de suivi du bot de trading
document.addEventListener('DOMContentLoaded', function() {
    // Elements DOM
    const currentDateElement = document.getElementById('current-date');
    const connectionStatusElement = document.getElementById('connection-status');
    const refreshBtn = document.getElementById('refresh-btn');
    const totalPnlElement = document.getElementById('total-pnl');
    const winRateElement = document.getElementById('win-rate');
    const totalTradesElement = document.getElementById('total-trades');
    const activePositionsElement = document.getElementById('active-positions');
    const recentTradesBody = document.getElementById('recent-trades-body');

    // Afficher la date actuelle
    const now = new Date();
    currentDateElement.textContent = now.toLocaleDateString('fr-FR', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });

    // Fonction pour charger les données
    async function loadData() {
        try {
            // Mise à jour du statut
            connectionStatusElement.textContent = 'Connexion...';
            connectionStatusElement.className = 'status-active';

            // Charger les métriques
            const metricsResponse = await fetch('/api/metrics');
            const metrics = await metricsResponse.json();

            // Charger les graphiques
            const chartsResponse = await fetch('/api/charts');
            const charts = await chartsResponse.json();

            // Charger l'historique
            const historyResponse = await fetch('/api/history');
            const history = await historyResponse.json();

            // Mettre à jour les éléments de la page
            updateMetrics(metrics);
            renderCharts(charts);
            renderRecentTrades(history.deals || []);

            // Mise à jour du statut
            connectionStatusElement.textContent = 'Connecté';
            connectionStatusElement.className = 'status-active';

        } catch (error) {
            console.error('Erreur lors du chargement des données:', error);
            connectionStatusElement.textContent = 'Erreur de connexion';
            connectionStatusElement.className = 'status-inactive';
            showError('Impossible de charger les données. Veuillez vérifier la connexion au serveur.');
        }
    }

    // Fonction pour mettre à jour les métriques
    function updateMetrics(metrics) {
        if (metrics.total_pnl !== undefined) {
            totalPnlElement.textContent = formatCurrency(metrics.total_pnl);
            totalPnlElement.className = metrics.total_pnl >= 0 ? 'metric-value positive' : 'metric-value negative';
        }

        if (metrics.win_rate !== undefined) {
            winRateElement.textContent = `${metrics.win_rate}%`;
            winRateElement.className = metrics.win_rate >= 50 ? 'metric-value positive' : 'metric-value negative';
        }

        if (metrics.total_trades !== undefined) {
            totalTradesElement.textContent = metrics.total_trades;
        }

        if (metrics.active_positions !== undefined) {
            activePositionsElement.textContent = metrics.active_positions;
        }
    }

    // Fonction pour afficher les erreurs
    function showError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error';
        errorDiv.textContent = message;

        const container = document.querySelector('.container');
        container.insertBefore(errorDiv, container.firstChild);

        // Supprimer l'erreur après quelques secondes
        setTimeout(() => {
            errorDiv.remove();
        }, 5000);
    }

    // Fonction pour formater les montants en devise
    function formatCurrency(amount) {
        return new Intl.NumberFormat('fr-FR', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2
        }).format(amount);
    }

    // Fonction pour afficher les graphiques
    function renderCharts(charts) {
        if (charts.cumulative_pnl) {
            Plotly.newPlot('cumulative-pnl-chart', charts.cumulative_pnl.data, charts.cumulative_pnl.layout);
        }

        if (charts.daily_pnl) {
            Plotly.newPlot('daily-pnl-chart', charts.daily_pnl.data, charts.daily_pnl.layout);
        }

        if (charts.symbol_pnl) {
            Plotly.newPlot('symbol-pnl-chart', charts.symbol_pnl.data, charts.symbol_pnl.layout);
        }

        if (charts.win_rate) {
            Plotly.newPlot('win-rate-chart', charts.win_rate.data, charts.win_rate.layout);
        }
    }

    // Fonction pour afficher les derniers trades
    function renderRecentTrades(trades) {
        // Trier les trades par date décroissante et prendre les 10 plus récents
        const recentTrades = [...trades].sort((a, b) => new Date(b.time) - new Date(a.time)).slice(0, 10);

        // Effacer le tableau existant
        recentTradesBody.innerHTML = '';

        // Remplir le tableau avec les données
        recentTrades.forEach(trade => {
            const row = document.createElement('tr');
            
            // Déterminer la classe pour le PnL
            const pnlClass = trade.profit >= 0 ? 'positive' : 'negative';
            
            row.innerHTML = `
                <td>${new Date(trade.time).toLocaleString('fr-FR')}</td>
                <td>${trade.symbol}</td>
                <td>${trade.type}</td>
                <td>${trade.volume}</td>
                <td>${trade.price.toFixed(5)}</td>
                <td class="${pnlClass}">${formatCurrency(trade.profit)}</td>
            `;
            
            recentTradesBody.appendChild(row);
        });
    }

    // Gestionnaire de clic pour le bouton d'actualisation
    refreshBtn.addEventListener('click', loadData);

    // Charger les données initiales
    loadData();

    // Actualisation automatique toutes les 30 secondes
    setInterval(loadData, 30000);
});