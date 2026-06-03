"""
基金驾驶舱 — 数据库模块（SQLite）

持仓管理：增删改查 + 市值实时计算
"""
import sqlite3
import os
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "portfolio.db")


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT    NOT NULL,
            name        TEXT    NOT NULL DEFAULT '',
            shares      REAL    NOT NULL CHECK(shares > 0),
            cost_nav    REAL    NOT NULL CHECK(cost_nav > 0),
            added_at    TEXT    NOT NULL,
            notes       TEXT    DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def add_holding(code: str, name: str, shares: float, cost_nav: float, notes: str = "") -> int:
    """添加持仓，返回 id"""
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO holdings (code, name, shares, cost_nav, added_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (code, name, shares, cost_nav, datetime.now().isoformat(), notes),
    )
    conn.commit()
    holding_id = cursor.lastrowid
    conn.close()
    return holding_id


def get_all_holdings() -> list:
    """获取全部持仓"""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM holdings ORDER BY added_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_holding(holding_id: int) -> dict | None:
    """获取单条持仓"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_holding(holding_id: int, shares: float | None = None, cost_nav: float | None = None, notes: str | None = None) -> bool:
    """更新持仓，返回是否更新成功"""
    conn = _get_conn()
    fields = []
    values = []
    if shares is not None:
        fields.append("shares = ?")
        values.append(shares)
    if cost_nav is not None:
        fields.append("cost_nav = ?")
        values.append(cost_nav)
    if notes is not None:
        fields.append("notes = ?")
        values.append(notes)
    if not fields:
        conn.close()
        return False
    values.append(holding_id)
    conn.execute(f"UPDATE holdings SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed


def delete_holding(holding_id: int) -> bool:
    """删除持仓"""
    conn = _get_conn()
    conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed
