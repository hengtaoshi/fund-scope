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
    conn.commit()
    conn.close()


def add_holding(user_id: int, code: str, name: str, shares: float, cost_nav: float, notes: str = "") -> int:
    """添加持仓，返回 id"""
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO holdings (user_id, code, name, shares, cost_nav, added_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, code, name, shares, cost_nav, datetime.now().isoformat(), notes),
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


def update_holding(holding_id: int, user_id: int, shares: float | None = None, cost_nav: float | None = None, notes: str | None = None) -> bool:
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
