"""SQLite-backed persistent trade history — one physical table PER MT5
account (trade_history_<login>), all in the same DB file.

Every function takes account_login and operates only on that account's own
table — there is no code path that can read or write across accounts by
accident. This replaced an earlier design that kept one shared table with a
symbol + account_login column and relied on WHERE filters for isolation;
that worked right up until a brief window where a bug meant some rows got
written with the wrong account_login, silently merging a demo account's
history into what looked like the live account's real trade history (and
vice versa). Separate tables make that class of bug structurally impossible
— there's no shared table left to leak across.

Previously trade history + stats lived only in an in-memory deque
(bot_runner.BotState.trade_history), so ANY process restart — a Windows
update, a crash, a manual relaunch — silently wiped all of it. On top of
that, the profit recorded per trade came straight from MT5's
position.profit, which excludes commission/swap, so the numbers shown never
matched what actually happened to the account balance.

This module fixes both: every closed trade is written to disk immediately
(insert_trade), and a background reconciliation pass (see
bot_runner.SymbolBot._reconcile_commissions) patches in the real
commission/swap once MT5's own deal history catches up — it can lag the
terminal by hours, so we don't block on it, we correct the row once it's
available.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "trade_history.db"

_TABLE_COLUMNS = """
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    ticket INTEGER UNIQUE,
    side TEXT,
    mode TEXT,
    opened_at TEXT,
    closed_at TEXT,
    closed_ts REAL,
    price_open REAL,
    sl REAL,
    tp REAL,
    gross_profit REAL,   -- raw position.profit at close time (no commission/swap)
    commission REAL,     -- filled in once MT5 deal history catches up
    swap REAL,
    profit REAL,         -- net = what actually hit the account (gross + commission + swap)
    close_reason TEXT,
    open_reason TEXT,
    reconciled INTEGER DEFAULT 0
"""
# ticket is UNIQUE (tickets never repeat within one account) — this is what
# makes insert_trade's INSERT OR IGNORE safe: the live tick-based close
# detector and the periodic broker-history sync can both race to record the
# same closed ticket, and previously both could win, double-counting that
# trade's profit in every stats total.

_SYNC_CUTOFF_TABLE = """
CREATE TABLE IF NOT EXISTS sync_cutoff (
    symbol TEXT NOT NULL,
    account_login INTEGER NOT NULL,
    cutoff_ts REAL NOT NULL,
    PRIMARY KEY (symbol, account_login)
)
"""
# Broker-history sync (bot_runner.SymbolBot._sync_trades_from_broker) always
# looks back N days into MT5's own deal history and re-imports anything not
# yet in our local table — so simply DELETEing a row doesn't keep it gone,
# the very next sync sees it as "missing" and pulls it straight back in.
# sync_cutoff records "don't look before this point in time" per
# (symbol, account) so an intentional cleanup (see set_sync_cutoff) sticks.


def _table_name(account_login: int) -> str:
    """trade_history_<login> — account_login must resolve to a plain
    positive integer (an MT5 login). Stripped defensively before splicing
    into SQL (table names can't be bound as query parameters)."""
    if account_login is None:
        raise ValueError("account_login is required — no MT5 account connected yet?")
    digits = re.sub(r"\D", "", str(account_login))
    if not digits:
        raise ValueError(f"invalid account_login: {account_login!r}")
    return f"trade_history_{digits}"


def _ensure_table(conn: sqlite3.Connection, table: str):
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({_TABLE_COLUMNS})')
    conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_closed_ts" ON "{table}"(closed_ts DESC)')
    conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_ticket" ON "{table}"(ticket)')
    conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_symbol" ON "{table}"(symbol)')


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(account_login: int):
    conn = _connect()
    try:
        _ensure_table(conn, _table_name(account_login))
        conn.commit()
    finally:
        conn.close()


def insert_trade(entry: dict, ts: float, symbol: str, account_login: int,
                  commission: Optional[float] = None, swap: Optional[float] = None,
                  net_profit: Optional[float] = None, reconciled: bool = False) -> int:
    """entry: the same dict shape bot_runner has always built for a closed trade.
    ts: epoch seconds, used for ordering/pagination (closed_at is just a display string).
    symbol: which instrument this trade was on (e.g. "USA500", "XAUUSD").
    account_login: which MT5 account this trade happened on — selects which
    physical table the row goes into.
    commission/swap/net_profit/reconciled: pass these when the caller already has
    real broker figures (e.g. the broker-history sync); otherwise the row is
    inserted with gross profit only and picked up by the reconciliation pass.
    """
    table = _table_name(account_login)
    gross = entry.get("profit")
    net = gross if net_profit is None else net_profit
    conn = _connect()
    try:
        _ensure_table(conn, table)
        # OR IGNORE + the UNIQUE(ticket) constraint: the live tick-based
        # close detector and the periodic broker-history sync can both spot
        # the same closed ticket in the same window and both try to record
        # it — without this, both inserts succeeded and the trade's profit
        # got double-counted in every stats total (found 2026-08-11: two
        # rows for the same ticket, ~1 second apart).
        cur = conn.execute(
            f"""INSERT OR IGNORE INTO "{table}"
               (symbol, ticket, side, mode, opened_at, closed_at, closed_ts, price_open, sl, tp,
                gross_profit, commission, swap, profit, close_reason, open_reason, reconciled)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                symbol, entry.get("ticket"), entry.get("side"), entry.get("mode"),
                entry.get("opened_at"), entry.get("closed_at"), ts,
                entry.get("price_open"), entry.get("sl"), entry.get("tp"),
                gross, commission, swap, net,
                entry.get("close_reason"), entry.get("open_reason"),
                1 if reconciled else 0,
            ),
        )
        conn.commit()
        return cur.lastrowid if cur.rowcount else None
    finally:
        conn.close()


def get_sync_cutoff(symbol: str, account_login: int) -> Optional[float]:
    """Epoch seconds before which the broker-history sync should not import
    anything for this (symbol, account) — set after an intentional cleanup
    so deleted rows don't get silently re-imported on the next sync."""
    conn = _connect()
    try:
        conn.execute(_SYNC_CUTOFF_TABLE)
        row = conn.execute(
            "SELECT cutoff_ts FROM sync_cutoff WHERE symbol = ? AND account_login = ?",
            (symbol, account_login),
        ).fetchone()
        return row["cutoff_ts"] if row else None
    finally:
        conn.close()


def set_sync_cutoff(symbol: str, account_login: int, cutoff_ts: float):
    conn = _connect()
    try:
        conn.execute(_SYNC_CUTOFF_TABLE)
        conn.execute(
            "INSERT INTO sync_cutoff (symbol, account_login, cutoff_ts) VALUES (?,?,?) "
            "ON CONFLICT(symbol, account_login) DO UPDATE SET cutoff_ts = excluded.cutoff_ts",
            (symbol, account_login, cutoff_ts),
        )
        conn.commit()
    finally:
        conn.close()


def get_page(page: int, page_size: int, account_login: int, symbol: Optional[str] = None) -> dict:
    """symbol=None combines every symbol within this one account's table."""
    table = _table_name(account_login)
    page = max(1, page)
    page_size = max(1, min(page_size, 50))  # hard cap — max 50 trades per page
    offset = (page - 1) * page_size
    where = "WHERE symbol = ?" if symbol else ""
    params = (symbol,) if symbol else ()
    conn = _connect()
    try:
        _ensure_table(conn, table)
        total = conn.execute(f'SELECT COUNT(*) c FROM "{table}" {where}', params).fetchone()["c"]
        rows = conn.execute(
            f'SELECT * FROM "{table}" {where} ORDER BY closed_ts DESC, id DESC LIMIT ? OFFSET ?',
            (*params, page_size, offset),
        ).fetchall()
        return {
            "trades": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }
    finally:
        conn.close()


def get_stats(account_login: int, symbol: Optional[str] = None) -> dict:
    """Aggregate straight from the persisted rows — guarantees stats always
    match the trades actually listed in the history table (same source),
    including the reconciled (commission-adjusted) profit. symbol=None
    combines every symbol within this account."""
    table = _table_name(account_login)
    where = "WHERE symbol = ?" if symbol else ""
    params = (symbol,) if symbol else ()
    sql = f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) AS losses,
            COALESCE(SUM(profit), 0) AS profit,
            SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) AS buy_trades,
            SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) AS sell_trades
        FROM "{table}" {where}
    """
    # NOTE: total is COUNT(*) of every row — not wins+losses. MT5/broker stats
    # ("Trades: 18", "Profit Trades: 11", "Loss Trades: 7") count a breakeven
    # (exact $0.00 net) closed trade in the total without putting it in either
    # bucket.
    conn = _connect()
    try:
        _ensure_table(conn, table)
        row = conn.execute(sql, params).fetchone()
        total = row["total"] or 0
        wins = row["wins"] or 0
        return {
            "total": total,
            "wins": wins,
            "losses": row["losses"] or 0,
            "profit": round(row["profit"] or 0, 2),
            "win_rate": round(wins / total * 100, 2) if total else 0,
            "buy_trades": row["buy_trades"] or 0,
            "sell_trades": row["sell_trades"] or 0,
        }
    finally:
        conn.close()


def find_unreconciled(symbol: str, account_login: int, limit: int = 25) -> list:
    table = _table_name(account_login)
    conn = _connect()
    try:
        _ensure_table(conn, table)
        rows = conn.execute(
            f'SELECT * FROM "{table}" WHERE reconciled = 0 AND symbol = ? ORDER BY closed_ts ASC LIMIT ?',
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_commission(row_id: int, account_login: int, commission: float, swap: float, net_profit: float):
    table = _table_name(account_login)
    conn = _connect()
    try:
        conn.execute(
            f'UPDATE "{table}" SET commission=?, swap=?, profit=?, reconciled=1 WHERE id=?',
            (commission, swap, net_profit, row_id),
        )
        conn.commit()
    finally:
        conn.close()


def count_rows(account_login: int, symbol: Optional[str] = None) -> int:
    table = _table_name(account_login)
    where = "WHERE symbol = ?" if symbol else ""
    params = (symbol,) if symbol else ()
    conn = _connect()
    try:
        _ensure_table(conn, table)
        return conn.execute(f'SELECT COUNT(*) c FROM "{table}" {where}', params).fetchone()["c"]
    finally:
        conn.close()


def known_tickets(symbol: str, account_login: int) -> set:
    """All position tickets already recorded for this symbol, within this
    account's own table — used to diff against MT5's own closed-deal
    history so nothing falls out of sync (see
    bot_runner.SymbolBot._sync_trades_from_broker)."""
    table = _table_name(account_login)
    conn = _connect()
    try:
        _ensure_table(conn, table)
        rows = conn.execute(f'SELECT DISTINCT ticket FROM "{table}" WHERE symbol = ?', (symbol,)).fetchall()
        return {r["ticket"] for r in rows}
    finally:
        conn.close()
