"""
基金范围 — 数据库模块（SQLite）

持仓管理：增删改查 + 市值实时计算
"""
import sqlite3
import os
from datetime import datetime

_UNSET = object()  # sentinel：区分"不更新该字段"与"显式设为 None/NULL"

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
            user_id     INTEGER NOT NULL DEFAULT 1,
            code        TEXT    NOT NULL,
            name        TEXT    NOT NULL DEFAULT '',
            shares      REAL    NOT NULL CHECK(shares > 0),
            cost_nav    REAL    NOT NULL CHECK(cost_nav > 0),
            added_at    TEXT    NOT NULL,
            notes       TEXT    DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    # 旧表迁移：若 user_id 列不存在则添加
    cursor = conn.execute("PRAGMA table_info(holdings)")
    cols = [row["name"] for row in cursor.fetchall()]
    if "user_id" not in cols:
        conn.execute("ALTER TABLE holdings ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
    # 定投累计投入金额字段
    if "total_invested" not in cols:
        conn.execute("ALTER TABLE holdings ADD COLUMN total_invested REAL DEFAULT NULL")
    if "dca_start_date" not in cols:
        conn.execute("ALTER TABLE holdings ADD COLUMN dca_start_date TEXT DEFAULT NULL")
    if "dca_amount" not in cols:
        conn.execute("ALTER TABLE holdings ADD COLUMN dca_amount REAL DEFAULT NULL")
    if "dca_frequency" not in cols:
        conn.execute("ALTER TABLE holdings ADD COLUMN dca_frequency TEXT DEFAULT NULL")
    if "dca_end_date" not in cols:
        conn.execute("ALTER TABLE holdings ADD COLUMN dca_end_date TEXT DEFAULT NULL")
    if "dca_initial" not in cols:
        conn.execute("ALTER TABLE holdings ADD COLUMN dca_initial REAL DEFAULT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holdings_user_id ON holdings(user_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            email           TEXT    NOT NULL UNIQUE,
            password_hash   TEXT    NOT NULL,
            created_at      TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS verification_codes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT    NOT NULL,
            code        TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            used        INTEGER DEFAULT 0
        )
    """)
    # 交易流水表（v2 新增：记录每一笔买卖/分红）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL DEFAULT 1,
            fund_code   TEXT    NOT NULL,
            fund_name   TEXT    NOT NULL DEFAULT '',
            type        TEXT    NOT NULL CHECK(type IN ('buy', 'sell', 'dividend')),
            shares      REAL    NOT NULL,
            price       REAL    NOT NULL,
            amount      REAL    NOT NULL,
            fee         REAL    DEFAULT 0,
            tx_date     TEXT    NOT NULL,
            note        TEXT    DEFAULT '',
            created_at  TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    # 自选列表表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL DEFAULT 1,
            code            TEXT    NOT NULL,
            name            TEXT    NOT NULL DEFAULT '',
            fund_type       TEXT    DEFAULT '',
            notes           TEXT    DEFAULT '',
            target_price    REAL    DEFAULT NULL,
            alert_enabled   INTEGER DEFAULT 0,
            added_at        TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_user_code ON watchlist(user_id, code)")
    # 索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_user_fund ON transactions(user_id, fund_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(tx_date)")
    conn.commit()
    conn.close()


def add_holding(user_id: int, code: str, name: str, shares: float, cost_nav: float, notes: str = "", total_invested: float = None, dca_start_date: str = None, dca_amount: float = None, dca_frequency: str = None, dca_end_date: str = None, dca_initial: float = None) -> int:
    """添加持仓，返回 id"""
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO holdings (user_id, code, name, shares, cost_nav, added_at, notes, total_invested, dca_start_date, dca_amount, dca_frequency, dca_end_date, dca_initial) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, code, name, shares, cost_nav, datetime.now().isoformat(), notes, total_invested, dca_start_date, dca_amount, dca_frequency, dca_end_date, dca_initial),
    )
    conn.commit()
    holding_id = cursor.lastrowid
    conn.close()
    return holding_id


def get_all_holdings(user_id: int) -> list:
    """获取指定用户全部持仓"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM holdings WHERE user_id = ? ORDER BY added_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_holding(holding_id: int, user_id: int) -> dict | None:
    """获取单条持仓（校验所属用户）"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM holdings WHERE id = ? AND user_id = ?", (holding_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_holding(holding_id: int, user_id: int, shares: float | None = None, cost_nav: float | None = None, notes: str | None = None, total_invested: float | None = None, dca_start_date: str | None = None, dca_amount: float | None = None, dca_frequency: str | None = None, dca_end_date: str | None = _UNSET, dca_initial: float | None = None) -> bool:
    """更新持仓（校验所属用户），返回是否更新成功"""
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
    if total_invested is not None:
        fields.append("total_invested = ?")
        values.append(total_invested)
    if dca_start_date is not None:
        fields.append("dca_start_date = ?")
        values.append(dca_start_date)
    if dca_amount is not None:
        fields.append("dca_amount = ?")
        values.append(dca_amount)
    if dca_frequency is not None:
        fields.append("dca_frequency = ?")
        values.append(dca_frequency)
    if dca_end_date is not _UNSET:
        fields.append("dca_end_date = ?")
        values.append(dca_end_date)  # None = 显式清空为 NULL
    if dca_initial is not None:
        fields.append("dca_initial = ?")
        values.append(dca_initial)
    if not fields:
        conn.close()
        return False
    values.append(holding_id)
    values.append(user_id)
    conn.execute(
        f"UPDATE holdings SET {', '.join(fields)} WHERE id = ? AND user_id = ?", values
    )
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed


def delete_holding(holding_id: int, user_id: int) -> bool:
    """删除持仓（校验所属用户）"""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM holdings WHERE id = ? AND user_id = ?", (holding_id, user_id)
    )
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed


# ====== 用户系统 ======


def get_user_by_email(email: str) -> dict | None:
    """通过邮箱获取用户"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(email: str, password_hash: str) -> int:
    """创建用户，返回 id"""
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
        (email, password_hash, datetime.now().isoformat()),
    )
    conn.commit()
    uid = cursor.lastrowid
    conn.close()
    return uid


def save_verification_code(email: str, code: str):
    """保存验证码"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO verification_codes (email, code, created_at) VALUES (?, ?, ?)",
        (email, code, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_latest_code(email: str) -> dict | None:
    """获取最新的未使用验证码"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM verification_codes WHERE email = ? AND used = 0 ORDER BY id DESC LIMIT 1",
        (email,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_code_used(code_id: int):
    """标记验证码已使用"""
    conn = _get_conn()
    conn.execute("UPDATE verification_codes SET used = 1 WHERE id = ?", (code_id,))
    conn.commit()
    conn.close()


def clean_expired_codes(hours: int = 1):
    """清理超过指定小时的验证码"""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM verification_codes WHERE created_at < datetime('now', ?)",
        (f'-{hours} hours',),
    )
    conn.commit()
    conn.close()


# ====== 交易流水 ======


def add_transaction(user_id: int, fund_code: str, fund_name: str, tx_type: str,
                    shares: float, price: float, amount: float, tx_date: str,
                    fee: float = 0, note: str = "") -> int:
    """添加一条交易记录，返回 id"""
    conn = _get_conn()
    cursor = conn.execute(
        """INSERT INTO transactions
           (user_id, fund_code, fund_name, type, shares, price, amount, fee, tx_date, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, fund_code, fund_name, tx_type, shares, price, amount, fee,
         tx_date, note, datetime.now().isoformat()),
    )
    conn.commit()
    tx_id = cursor.lastrowid
    conn.close()
    return tx_id


def get_transactions(user_id: int, fund_code: str = None) -> list:
    """获取交易记录，可选按基金筛选，按日期降序"""
    conn = _get_conn()
    if fund_code:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND fund_code = ? ORDER BY tx_date DESC, id DESC",
            (user_id, fund_code),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY tx_date DESC, id DESC",
            (user_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_transaction(tx_id: int, user_id: int) -> bool:
    """删除交易记录"""
    conn = _get_conn()
    conn.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id))
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed


def get_holdings_from_transactions(user_id: int) -> list:
    """从交易流水汇总当前持仓（基金代码维度）"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT fund_code, fund_name,
                  SUM(CASE WHEN type='buy' THEN shares WHEN type='sell' THEN -shares ELSE 0 END) as total_shares,
                  SUM(CASE WHEN type='buy' THEN amount ELSE 0 END) as total_bought,
                  SUM(CASE WHEN type='sell' THEN amount ELSE 0 END) as total_sold,
                  SUM(CASE WHEN type='buy' THEN amount ELSE 0 END)
                  - SUM(CASE WHEN type='sell' THEN amount ELSE 0 END) as net_cost,
                  COUNT(*) as tx_count,
                  MAX(tx_date) as last_tx_date
           FROM transactions
           WHERE user_id = ?
           GROUP BY fund_code
           HAVING total_shares > 0.001
           ORDER BY last_tx_date DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ====== 自选列表 ======


def get_watchlist(user_id: int) -> list:
    """获取用户全部自选"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM watchlist WHERE user_id = ? ORDER BY added_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_watchlist(user_id: int, code: str, name: str, fund_type: str = "",
                  notes: str = "", target_price: float = None,
                  alert_enabled: bool = False) -> dict:
    """添加自选，返回新记录"""
    conn = _get_conn()
    # 检查是否已存在
    existing = conn.execute(
        "SELECT id FROM watchlist WHERE user_id = ? AND code = ?",
        (user_id, code),
    ).fetchone()
    if existing:
        conn.close()
        return {"id": existing["id"], "exists": True}
    cursor = conn.execute(
        """INSERT INTO watchlist
           (user_id, code, name, fund_type, notes, target_price, alert_enabled, added_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, code, name, fund_type, notes, target_price,
         1 if alert_enabled else 0, datetime.now().isoformat()),
    )
    conn.commit()
    wid = cursor.lastrowid
    conn.close()
    return {"id": wid, "exists": False}


def delete_watchlist(watch_id: int, user_id: int) -> bool:
    """删除自选"""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM watchlist WHERE id = ? AND user_id = ?",
        (watch_id, user_id),
    )
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed


def update_watchlist(watch_id: int, user_id: int,
                     notes: str = None, target_price: float = None,
                     alert_enabled: bool = None) -> bool:
    """更新自选备注/提醒价"""
    conn = _get_conn()
    fields = []
    values = []
    if notes is not None:
        fields.append("notes = ?")
        values.append(notes)
    if target_price is not None:
        fields.append("target_price = ?")
        values.append(target_price)
    if alert_enabled is not None:
        fields.append("alert_enabled = ?")
        values.append(1 if alert_enabled else 0)
    if not fields:
        conn.close()
        return False
    values.append(watch_id)
    values.append(user_id)
    conn.execute(
        f"UPDATE watchlist SET {', '.join(fields)} WHERE id = ? AND user_id = ?",
        values,
    )
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed
