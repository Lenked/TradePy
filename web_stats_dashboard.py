"""
Backend Flask pour le dashboard de suivi du bot de trading
Se connecte à MetaTrader pour récupérer les données de trading
"""
import os
import json
import pandas as pd
from datetime import datetime, timedelta
import MetaTrader5 as mt5
from flask import Flask, render_template, jsonify, send_from_directory
import plotly
import plotly.graph_objs as go
import plotly.express as px
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

app = Flask(__name__, static_folder='frontend')

def connect_to_mt5():
    """Connexion au terminal MT5"""
    # Initialiser la connexion MT5
    if not mt5.initialize():
        print("Échec de l'initialisation, code erreur =", mt5.last_error())
        return False
    
    # Récupérer les identifiants depuis les variables d'environnement
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")
    
    # Tentative de connexion si les identifiants sont fournis
    if login and password and server:
        authorized = mt5.login(int(login), password=password, server=server)
        if authorized:
            print(f"Connecté au compte #{login} sur {server}")
            return True
        else:
            print("Échec de la connexion au compte, code erreur =", mt5.last_error())
            return False
    else:
        print("Identifiants MT5 non trouvés dans les variables d'environnement")
        return False

def get_trading_history():
    """Récupérer l'historique de trading depuis le compte MT5"""
    if not mt5.initialize():
        if not connect_to_mt5():
            return {'deals': [], 'positions': []}
    
    # Récupérer les transactions pour les 180 derniers jours (ajustable)
    to_date = datetime.now()
    from_date = to_date - timedelta(days=180)  # 6 mois d'historique
    
    # Récupérer les deals (transactions)
    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None:
        print("Aucun deal trouvé ou erreur survenue:", mt5.last_error())
        return {'deals': [], 'positions': []}
    
    # Récupérer les positions ouvertes
    positions = mt5.positions_get()
    if positions is None:
        print("Aucune position trouvée ou erreur survenue:", mt5.last_error())
        positions = []
    
    # Convertir les deals en liste de dictionnaires
    deals_list = []
    for deal in deals:
        # Pour les deals MT5, il peut y avoir plusieurs types de deals (ouverture, fermeture, etc.)
        # Le profit réel peut être dans différents champs selon le type de deal
        commission = getattr(deal, 'commission', 0.0) or 0.0
        swap = getattr(deal, 'swap', 0.0) or 0.0
        profit = getattr(deal, 'profit', 0.0) or 0.0
        
        # Selon la documentation MT5, certains deals peuvent représenter des frais ou des ajustements
        # et ne pas refléter le profit final d'une position fermée
        deal_type = getattr(deal, 'type', -1)
        
        # Créer le dictionnaire de deal
        deal_dict = {
            'ticket': getattr(deal, 'ticket', 0),
            'time': datetime.fromtimestamp(getattr(deal, 'time', 0)).isoformat() if hasattr(deal, 'time') and getattr(deal, 'time', 0) > 0 else '',
            'type': 'BUY' if getattr(deal, 'type', -1) == 0 else 'SELL' if getattr(deal, 'type', -1) == 1 else 'OTHER',
            'entry_type': getattr(deal, 'entry', -1),  # ENTRY_IN=0, ENTRY_OUT=1, ENTRY_REVERSE=2
            'symbol': getattr(deal, 'symbol', ''),
            'volume': getattr(deal, 'volume', 0.0),
            'price': getattr(deal, 'price', 0.0),
            'commission': commission,
            'swap': swap,
            'profit': profit,
            'comment': getattr(deal, 'comment', ''),
            'magic': getattr(deal, 'magic', 0),  # Numéro magique éventuel
            'order': getattr(deal, 'order', 0)   # Numéro d'ordre associé
        }
        deals_list.append(deal_dict)
    
    # Convertir les positions en liste de dictionnaires
    positions_list = []
    for pos in positions:
        pos_dict = {
            'ticket': getattr(pos, 'ticket', 0),
            'time': datetime.fromtimestamp(getattr(pos, 'time', 0)).isoformat() if hasattr(pos, 'time') and getattr(pos, 'time', 0) > 0 else '',
            'type': 'BUY' if getattr(pos, 'type', -1) == 0 else 'SELL' if getattr(pos, 'type', -1) == 1 else 'OTHER',
            'symbol': getattr(pos, 'symbol', ''),
            'volume': getattr(pos, 'volume', 0.0),
            'price_open': getattr(pos, 'price_open', 0.0),
            'price_current': getattr(pos, 'price_current', 0.0),
            'sl': getattr(pos, 'sl', 0.0),
            'tp': getattr(pos, 'tp', 0.0),
            'profit': getattr(pos, 'profit', 0.0)
        }
        positions_list.append(pos_dict)
    
    print(f"Récupéré {len(deals_list)} deals et {len(positions_list)} positions")
    
    # Filtrer les deals pour ne conserver que les fermetures de positions (ENTRY_OUT)
    # Ces deals représentent généralement le profit/loss final
    filtered_deals = [deal for deal in deals_list if deal['entry_type'] == 1]  # ENTRY_OUT
    
    print(f"Filtré pour ne garder que {len(filtered_deals)} deals de fermeture")
    
    return {
        'deals': filtered_deals,  # Utiliser les deals filtrés
        'positions': positions_list
    }

def calculate_metrics(history_data):
    """Calculer les métriques de trading à partir des données d'historique"""
    deals = history_data.get('deals', [])
    positions = history_data.get('positions', [])
    
    if not deals:
        return {
            'total_trades': 0,
            'profitable_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'avg_profit': 0,
            'avg_loss': 0,
            'profit_factor': 0,
            'max_drawdown': 0,
            'symbol_pnl': {},
            'symbol_trades': {},
            'daily_pnl': {},
            'active_positions': len(positions)
        }
    
    # Filtrer les deals avec des profits non nuls pour éviter les erreurs de calcul
    valid_deals = [deal for deal in deals if isinstance(deal.get('profit'), (int, float)) and deal['profit'] != 0]
    if not valid_deals:
        # Si tous les profits sont zéro, inclure quand même tous les deals
        valid_deals = deals
    
    df = pd.DataFrame(valid_deals)
    if df.empty:
        df = pd.DataFrame(deals)  # Utiliser tous les deals si aucun n'a de profit non nul
    
    # S'assurer que la colonne 'time' est au bon format
    if not df.empty and 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df = df.dropna(subset=['time'])  # Supprimer les lignes avec des dates invalides
    
    # Calculer les métriques
    total_trades = len(df)
    profitable_trades = len(df[df['profit'] > 0]) if not df.empty else 0
    losing_trades = len(df[df['profit'] < 0]) if not df.empty else 0
    
    win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0
    total_pnl = df['profit'].sum() if not df.empty else 0
    avg_profit = df[df['profit'] > 0]['profit'].mean() if profitable_trades > 0 else 0
    avg_loss = df[df['profit'] < 0]['profit'].mean() if losing_trades > 0 else 0
    
    gross_profit = df[df['profit'] > 0]['profit'].sum() if profitable_trades > 0 else 0
    gross_loss = abs(df[df['profit'] < 0]['profit'].sum()) if losing_trades > 0 else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
    
    # Calculer le drawdown
    df_sorted = df.sort_values('time') if not df.empty else df
    cumulative_pnl = df_sorted['profit'].cumsum() if not df_sorted.empty else pd.Series([])
    rolling_max = cumulative_pnl.expanding().max() if not cumulative_pnl.empty else pd.Series([])
    drawdown = cumulative_pnl - rolling_max
    max_drawdown = drawdown.min() if not drawdown.empty else 0
    
    # Regrouper par symbole
    symbol_pnl = {}
    symbol_trades = {}
    if not df.empty and 'symbol' in df.columns:
        symbol_pnl = df.groupby('symbol')['profit'].sum().to_dict()
        symbol_trades = df.groupby('symbol').size().to_dict()
    
    # Regrouper par date
    daily_pnl = {}
    if not df.empty and 'time' in df.columns:
        df['date'] = df['time'].dt.date.astype(str)
        daily_pnl = df.groupby('date')['profit'].sum().to_dict()
    
    metrics = {
        'total_trades': total_trades,
        'profitable_trades': profitable_trades,
        'losing_trades': losing_trades,
        'win_rate': round(win_rate, 2),
        'total_pnl': round(total_pnl, 2),
        'avg_profit': round(avg_profit, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 'inf',
        'max_drawdown': round(max_drawdown, 2),
        'symbol_pnl': symbol_pnl,
        'symbol_trades': symbol_trades,
        'daily_pnl': daily_pnl,
        'active_positions': len(positions)
    }
    
    return metrics

@app.route('/')
def index():
    """Page principale du dashboard"""
    return send_from_directory('frontend', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    """Servir les fichiers statiques"""
    return send_from_directory('frontend', path)

@app.route('/api/history')
def api_history():
    """Point d'API pour obtenir l'historique de trading"""
    history = get_trading_history()
    return jsonify(history)

@app.route('/api/metrics')
def api_metrics():
    """Point d'API pour obtenir les métriques calculées"""
    history = get_trading_history()
    metrics = calculate_metrics(history)
    return jsonify(metrics)

@app.route('/api/charts')
def api_charts():
    """Point d'API pour obtenir les données des graphiques"""
    history = get_trading_history()
    deals = history.get('deals', [])
    
    if not deals:
        empty_chart = {
            'data': [],
            'layout': {'title': 'Aucune donnée disponible'}
        }
        return jsonify({
            'cumulative_pnl': empty_chart,
            'daily_pnl': empty_chart,
            'symbol_pnl': empty_chart,
            'win_rate': empty_chart
        })
    
    df = pd.DataFrame(deals)
    df['time'] = pd.to_datetime(df['time'])
    df['date'] = df['time'].dt.date
    
    # Graphique PnL cumulatif
    df_sorted = df.sort_values('time')
    df_sorted['cumulative_pnl'] = df_sorted['profit'].cumsum()
    
    cumulative_chart = {
        'data': [{
            'x': df_sorted['time'].apply(lambda x: x.isoformat()).tolist(),
            'y': df_sorted['cumulative_pnl'].tolist(),
            'type': 'scatter',
            'mode': 'lines+markers',
            'name': 'PnL Cumulatif',
            'line': {'color': '#3498db', 'width': 3},
            'marker': {'size': 6}
        }],
        'layout': {
            'title': 'évolution Cumulative du PnL',
            'xaxis': {'title': 'Date'},
            'yaxis': {'title': 'PnL ($)', 'tickprefix': '$'},
            'hovermode': 'x unified',
            'showlegend': False
        }
    }
    
    # Graphique PnL quotidien
    daily_pnl = df.groupby('date')['profit'].sum().reset_index()
    daily_pnl['date'] = daily_pnl['date'].astype(str)
    
    daily_colors = ['#e74c3c' if x < 0 else '#2ecc71' for x in daily_pnl['profit']]
    
    daily_chart = {
        'data': [{
            'x': daily_pnl['date'].tolist(),
            'y': daily_pnl['profit'].tolist(),
            'type': 'bar',
            'marker': {'color': daily_colors},
            'name': 'PnL Quotidien'
        }],
        'layout': {
            'title': 'PnL Quotidien',
            'xaxis': {'title': 'Date'},
            'yaxis': {'title': 'PnL ($)', 'tickprefix': '$'},
            'showlegend': False
        }
    }
    
    # Graphique PnL par symbole
    symbol_pnl = df.groupby('symbol')['profit'].sum().reset_index()
    symbol_colors = ['#e74c3c' if x < 0 else '#2ecc71' for x in symbol_pnl['profit']]
    
    symbol_chart = {
        'data': [{
            'x': symbol_pnl['symbol'].tolist(),
            'y': symbol_pnl['profit'].tolist(),
            'type': 'bar',
            'marker': {'color': symbol_colors},
            'name': 'PnL par Symbole'
        }],
        'layout': {
            'title': 'PnL par Symbole',
            'xaxis': {'title': 'Symbole'},
            'yaxis': {'title': 'PnL ($)', 'tickprefix': '$'},
            'showlegend': False
        }
    }
    
    # Graphique taux de réussite
    profitable_count = len(df[df['profit'] > 0])
    losing_count = len(df[df['profit'] < 0])
    
    win_rate_chart = {
        'data': [{
            'labels': ['Trades Gagnants', 'Trades Perdants'],
            'values': [profitable_count, losing_count],
            'type': 'pie',
            'name': 'Taux de Réussite',
            'marker': {'colors': ['#2ecc71', '#e74c3c']}
        }],
        'layout': {
            'title': 'Répartition des Trades (Gagnants vs Perdants)'
        }
    }
    
    charts = {
        'cumulative_pnl': cumulative_chart,
        'daily_pnl': daily_chart,
        'symbol_pnl': symbol_chart,
        'win_rate': win_rate_chart
    }
    
    return jsonify(charts)

if __name__ == '__main__':
    # Se connecter à MT5
    if connect_to_mt5():
        print("Démarrage du serveur web...")
        app.run(debug=True, host='0.0.0.0', port=5000)
    else:
        print("Impossible de se connecter à MT5. Veuillez vérifier vos identifiants.")