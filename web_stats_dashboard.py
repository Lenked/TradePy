"""
Flask backend for the TradePy dashboard.
It reads trades/positions from MetaTrader 5 and exposes JSON APIs.
"""

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

app = Flask(__name__, static_folder="frontend")

ALLOWED_PERIODS = {7, 30, 90, 180}
DEFAULT_PERIOD_DAYS = 180


def _safe_float(value: Any) -> float:
    """Convert unknown values to float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_period_days() -> int:
    """Read and validate period from query string (?period=7|30|90|180)."""
    raw_value = request.args.get("period", str(DEFAULT_PERIOD_DAYS))
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_PERIOD_DAYS
    return parsed if parsed in ALLOWED_PERIODS else DEFAULT_PERIOD_DAYS


def connect_to_mt5() -> bool:
    """Initialize terminal and login to MT5 account if credentials are provided."""
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error())
        return False

    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if login and password and server:
        authorized = mt5.login(int(login), password=password, server=server)
        if authorized:
            print(f"Connected to account #{login} on {server}")
            return True
        print("MT5 login failed:", mt5.last_error())
        return False

    print("MT5 credentials not found in environment variables.")
    return False


def _build_deals_dataframe(deals: List[Dict[str, Any]]) -> pd.DataFrame:
    """Normalize deals list into a safe DataFrame."""
    if not deals:
        return pd.DataFrame(columns=["time", "profit", "symbol", "type", "volume"])

    df = pd.DataFrame(deals)

    if "time" not in df.columns:
        df["time"] = pd.NaT
    if "profit" not in df.columns:
        df["profit"] = 0.0
    if "symbol" not in df.columns:
        df["symbol"] = "N/A"
    if "type" not in df.columns:
        df["type"] = "OTHER"
    if "volume" not in df.columns:
        df["volume"] = 0.0

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["profit"] = pd.to_numeric(df["profit"], errors="coerce").fillna(0.0)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    df["symbol"] = df["symbol"].fillna("N/A").astype(str)
    df["type"] = df["type"].fillna("OTHER").astype(str)
    df = df.dropna(subset=["time"])
    return df


def get_trading_history(days: int = DEFAULT_PERIOD_DAYS) -> Dict[str, Any]:
    """Fetch and normalize trading history from MT5 for the selected period."""
    if not mt5.initialize():
        if not connect_to_mt5():
            return {
                "deals": [],
                "positions": [],
                "period_days": days,
                "generated_at": datetime.utcnow().isoformat(),
            }

    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)

    deals_raw = mt5.history_deals_get(from_date, to_date)
    if deals_raw is None:
        print("No deals or MT5 history error:", mt5.last_error())
        deals_raw = []

    positions_raw = mt5.positions_get()
    if positions_raw is None:
        print("No open positions or MT5 error:", mt5.last_error())
        positions_raw = []

    deals_list: List[Dict[str, Any]] = []
    for deal in deals_raw:
        deal_type = getattr(deal, "type", -1)
        entry_type = getattr(deal, "entry", -1)
        timestamp = getattr(deal, "time", 0)
        deals_list.append(
            {
                "ticket": getattr(deal, "ticket", 0),
                "time": datetime.fromtimestamp(timestamp).isoformat() if timestamp else "",
                "type": "BUY" if deal_type == 0 else "SELL" if deal_type == 1 else "OTHER",
                "entry_type": entry_type,
                "symbol": getattr(deal, "symbol", ""),
                "volume": _safe_float(getattr(deal, "volume", 0.0)),
                "price": _safe_float(getattr(deal, "price", 0.0)),
                "commission": _safe_float(getattr(deal, "commission", 0.0)),
                "swap": _safe_float(getattr(deal, "swap", 0.0)),
                "profit": _safe_float(getattr(deal, "profit", 0.0)),
                "comment": getattr(deal, "comment", ""),
                "magic": getattr(deal, "magic", 0),
                "order": getattr(deal, "order", 0),
            }
        )

    # ENTRY_OUT generally represents position close with realized PnL.
    filtered_deals = [deal for deal in deals_list if deal["entry_type"] == 1]

    positions_list: List[Dict[str, Any]] = []
    for pos in positions_raw:
        pos_type = getattr(pos, "type", -1)
        timestamp = getattr(pos, "time", 0)
        positions_list.append(
            {
                "ticket": getattr(pos, "ticket", 0),
                "time": datetime.fromtimestamp(timestamp).isoformat() if timestamp else "",
                "type": "BUY" if pos_type == 0 else "SELL" if pos_type == 1 else "OTHER",
                "symbol": getattr(pos, "symbol", ""),
                "volume": _safe_float(getattr(pos, "volume", 0.0)),
                "price_open": _safe_float(getattr(pos, "price_open", 0.0)),
                "price_current": _safe_float(getattr(pos, "price_current", 0.0)),
                "sl": _safe_float(getattr(pos, "sl", 0.0)),
                "tp": _safe_float(getattr(pos, "tp", 0.0)),
                "profit": _safe_float(getattr(pos, "profit", 0.0)),
            }
        )

    return {
        "deals": filtered_deals,
        "positions": positions_list,
        "period_days": days,
        "generated_at": datetime.utcnow().isoformat(),
    }


def calculate_metrics(history_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate dashboard metrics from history payload."""
    deals = history_data.get("deals", [])
    positions = history_data.get("positions", [])
    df = _build_deals_dataframe(deals)

    open_positions_pnl = round(sum(_safe_float(pos.get("profit")) for pos in positions), 2)
    net_position_volume = round(
        sum(
            _safe_float(pos.get("volume")) if pos.get("type") == "BUY" else -_safe_float(pos.get("volume"))
            for pos in positions
        ),
        2,
    )

    if df.empty:
        return {
            "total_trades": 0,
            "profitable_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_profit": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "symbol_pnl": {},
            "symbol_trades": {},
            "daily_pnl": {},
            "active_positions": len(positions),
            "open_positions_pnl": open_positions_pnl,
            "net_position_volume": net_position_volume,
            "risk_status": "Stable",
            "alerts_count": 0,
        }

    df_sorted = df.sort_values("time")
    total_trades = int(len(df_sorted))
    profitable_trades = int((df_sorted["profit"] > 0).sum())
    losing_trades = int((df_sorted["profit"] < 0).sum())

    win_rate = (profitable_trades / total_trades) * 100 if total_trades else 0.0
    total_pnl = float(df_sorted["profit"].sum())
    avg_profit = float(df_sorted.loc[df_sorted["profit"] > 0, "profit"].mean()) if profitable_trades else 0.0
    avg_loss = float(df_sorted.loc[df_sorted["profit"] < 0, "profit"].mean()) if losing_trades else 0.0
    gross_profit = float(df_sorted.loc[df_sorted["profit"] > 0, "profit"].sum()) if profitable_trades else 0.0
    gross_loss = abs(float(df_sorted.loc[df_sorted["profit"] < 0, "profit"].sum())) if losing_trades else 0.0

    if gross_loss == 0:
        profit_factor: Any = "inf" if gross_profit > 0 else 0.0
    else:
        profit_factor = round(gross_profit / gross_loss, 2)

    cumulative_pnl = df_sorted["profit"].cumsum()
    rolling_max = cumulative_pnl.cummax()
    drawdown = cumulative_pnl - rolling_max
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    symbol_summary = df_sorted.groupby("symbol")["profit"].agg(["sum", "count"])
    symbol_pnl = {symbol: round(value, 2) for symbol, value in symbol_summary["sum"].to_dict().items()}
    symbol_trades = {symbol: int(value) for symbol, value in symbol_summary["count"].to_dict().items()}

    daily = df_sorted.copy()
    daily["date"] = daily["time"].dt.date.astype(str)
    daily_pnl = {date: round(value, 2) for date, value in daily.groupby("date")["profit"].sum().to_dict().items()}

    alerts_count = int(max_drawdown <= -1000) + int(win_rate < 45) + int(open_positions_pnl < -500)
    if max_drawdown <= -2000 or win_rate < 35:
        risk_status = "Alerte"
    elif max_drawdown <= -1000 or win_rate < 50:
        risk_status = "A surveiller"
    else:
        risk_status = "Stable"

    return {
        "total_trades": total_trades,
        "profitable_trades": profitable_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_profit": round(avg_profit, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": profit_factor,
        "max_drawdown": round(max_drawdown, 2),
        "symbol_pnl": symbol_pnl,
        "symbol_trades": symbol_trades,
        "daily_pnl": daily_pnl,
        "active_positions": len(positions),
        "open_positions_pnl": open_positions_pnl,
        "net_position_volume": net_position_volume,
        "risk_status": risk_status,
        "alerts_count": alerts_count,
    }


def _empty_chart(title: str) -> Dict[str, Any]:
    return {
        "data": [],
        "layout": {
            "title": title,
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "font": {"family": "Manrope, sans-serif", "color": "#10203A"},
        },
    }


def build_charts(deals: List[Dict[str, Any]], period_days: int) -> Dict[str, Any]:
    """Build Plotly payloads for the dashboard charts."""
    df = _build_deals_dataframe(deals)
    if df.empty:
        return {
            "cumulative_pnl": _empty_chart(f"PnL Cumulatif ({period_days} jours)"),
            "daily_pnl": _empty_chart("PnL Quotidien"),
            "symbol_pnl": _empty_chart("PnL par Symbole"),
            "win_rate": _empty_chart("Taux de reussite"),
        }

    df_sorted = df.sort_values("time").copy()
    df_sorted["cumulative_pnl"] = df_sorted["profit"].cumsum()

    cumulative_chart = {
        "data": [
            {
                "x": df_sorted["time"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
                "y": df_sorted["cumulative_pnl"].round(2).tolist(),
                "type": "scatter",
                "mode": "lines+markers",
                "line": {"color": "#0B6BFF", "width": 3},
                "marker": {"size": 6, "color": "#0B6BFF"},
                "hovertemplate": "%{x}<br>PnL cumule: $%{y:.2f}<extra></extra>",
            }
        ],
        "layout": {
            "title": f"PnL Cumulatif ({period_days} jours)",
            "margin": {"l": 30, "r": 20, "t": 40, "b": 30},
            "xaxis": {"showgrid": False},
            "yaxis": {"showgrid": True, "gridcolor": "#DDE7F7", "tickprefix": "$"},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "font": {"family": "Manrope, sans-serif", "color": "#10203A"},
            "showlegend": False,
            "hovermode": "x unified",
        },
    }

    daily_df = df_sorted.copy()
    daily_df["date"] = daily_df["time"].dt.date.astype(str)
    daily_pnl = daily_df.groupby("date")["profit"].sum().reset_index()
    daily_colors = ["#139C5A" if value >= 0 else "#D94848" for value in daily_pnl["profit"].tolist()]

    daily_chart = {
        "data": [
            {
                "x": daily_pnl["date"].tolist(),
                "y": daily_pnl["profit"].round(2).tolist(),
                "type": "bar",
                "marker": {"color": daily_colors},
                "hovertemplate": "%{x}<br>PnL: $%{y:.2f}<extra></extra>",
            }
        ],
        "layout": {
            "title": "PnL Quotidien",
            "margin": {"l": 30, "r": 10, "t": 40, "b": 30},
            "xaxis": {"showgrid": False, "tickangle": -30},
            "yaxis": {"showgrid": False, "tickprefix": "$"},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "font": {"family": "Manrope, sans-serif", "color": "#10203A"},
            "showlegend": False,
        },
    }

    symbol_df = (
        df_sorted.groupby("symbol", as_index=False)["profit"]
        .sum()
        .sort_values("profit", ascending=True)
        .tail(8)
    )
    symbol_colors = ["#139C5A" if value >= 0 else "#D94848" for value in symbol_df["profit"].tolist()]
    symbol_chart = {
        "data": [
            {
                "x": symbol_df["profit"].round(2).tolist(),
                "y": symbol_df["symbol"].tolist(),
                "type": "bar",
                "orientation": "h",
                "marker": {"color": symbol_colors},
                "hovertemplate": "%{y}<br>PnL: $%{x:.2f}<extra></extra>",
            }
        ],
        "layout": {
            "title": "PnL par Symbole",
            "margin": {"l": 90, "r": 20, "t": 40, "b": 20},
            "xaxis": {"showgrid": False, "tickprefix": "$"},
            "yaxis": {"showgrid": False},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "font": {"family": "Manrope, sans-serif", "color": "#10203A"},
            "showlegend": False,
        },
    }

    profitable_count = int((df_sorted["profit"] > 0).sum())
    losing_count = int((df_sorted["profit"] < 0).sum())
    if profitable_count + losing_count == 0:
        win_values = [1]
        win_labels = ["Aucun trade"]
        win_colors = ["#DCE6F7"]
    else:
        win_values = [profitable_count, losing_count]
        win_labels = ["Gagnants", "Perdants"]
        win_colors = ["#0B6BFF", "#E3ECFA"]

    win_rate_chart = {
        "data": [
            {
                "labels": win_labels,
                "values": win_values,
                "type": "pie",
                "hole": 0.62,
                "marker": {"colors": win_colors},
                "textinfo": "none",
                "hovertemplate": "%{label}: %{value}<extra></extra>",
                "sort": False,
            }
        ],
        "layout": {
            "title": "Taux de reussite",
            "margin": {"l": 10, "r": 10, "t": 40, "b": 10},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "font": {"family": "Manrope, sans-serif", "color": "#10203A"},
            "showlegend": False,
        },
    }

    return {
        "cumulative_pnl": cumulative_chart,
        "daily_pnl": daily_chart,
        "symbol_pnl": symbol_chart,
        "win_rate": win_rate_chart,
    }


def _build_dashboard_payload(period_days: int) -> Dict[str, Any]:
    """Build a full dashboard response in one MT5 fetch."""
    history = get_trading_history(period_days)
    metrics = calculate_metrics(history)
    charts = build_charts(history.get("deals", []), period_days)
    return {
        "period_days": period_days,
        "generated_at": datetime.utcnow().isoformat(),
        "history": history,
        "metrics": metrics,
        "charts": charts,
    }


@app.route("/")
def index() -> Any:
    return send_from_directory("frontend", "index.html")


@app.route("/<path:path>")
def static_files(path: str) -> Any:
    return send_from_directory("frontend", path)


@app.route("/api/dashboard")
def api_dashboard() -> Any:
    period_days = _parse_period_days()
    payload = _build_dashboard_payload(period_days)
    return jsonify(payload)


@app.route("/api/history")
def api_history() -> Any:
    period_days = _parse_period_days()
    history = get_trading_history(period_days)
    return jsonify(history)


@app.route("/api/metrics")
def api_metrics() -> Any:
    period_days = _parse_period_days()
    history = get_trading_history(period_days)
    metrics = calculate_metrics(history)
    return jsonify(metrics)


@app.route("/api/charts")
def api_charts() -> Any:
    period_days = _parse_period_days()
    history = get_trading_history(period_days)
    charts = build_charts(history.get("deals", []), period_days)
    return jsonify(charts)


if __name__ == "__main__":
    if connect_to_mt5():
        print("Starting web server...")
        app.run(debug=True, host="0.0.0.0", port=5000)
    else:
        print("Unable to connect to MT5. Check your credentials.")
