"""
取得したデータを保存するローカルデータベース(SQLite)まわりの処理。

SQLiteは、専用のサーバーを用意しなくても使える「ファイル1つのデータベース」。
このファイルは data/money.db に保存される(Gitには含めない)。
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR

DB_PATH = DATA_DIR / "money.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    mf_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    month TEXT NOT NULL,
    description TEXT NOT NULL,
    amount INTEGER NOT NULL,
    type TEXT NOT NULL,
    category TEXT,
    sub_category TEXT,
    account_name TEXT,
    transfer_target TEXT,
    is_transfer INTEGER NOT NULL DEFAULT 0,
    is_excluded INTEGER NOT NULL DEFAULT 0,
    scraped_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holdings_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    code TEXT,
    institution TEXT,
    quantity REAL,
    avg_cost_price REAL,
    unit_price REAL,
    balance INTEGER NOT NULL,
    daily_change INTEGER,
    unrealized_gain INTEGER,
    unrealized_gain_pct REAL,
    scraped_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_month ON transactions(month);
CREATE INDEX IF NOT EXISTS idx_holdings_snapshot_date ON holdings_snapshots(snapshot_date);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_transactions(conn: sqlite3.Connection, transactions: list[dict]) -> int:
    """
    取引データを保存する。同じ mf_id が既にあれば内容を上書きする(重複登録を防ぐため)。
    これにより、同じ月を何度取得しても件数が増え続けることはない。
    """
    scraped_at = _now_iso()
    rows = [
        (
            t["mf_id"],
            t["date"],
            t["date"][:7],  # month = "YYYY-MM"
            t["description"],
            t["amount"],
            t["type"],
            t.get("category"),
            t.get("sub_category"),
            t.get("account_name"),
            t.get("transfer_target"),
            int(t.get("is_transfer", False)),
            int(t.get("is_excluded", False)),
            scraped_at,
        )
        for t in transactions
        if t.get("mf_id")
    ]

    conn.executemany(
        """
        INSERT INTO transactions (
            mf_id, date, month, description, amount, type,
            category, sub_category, account_name, transfer_target,
            is_transfer, is_excluded, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mf_id) DO UPDATE SET
            date=excluded.date,
            month=excluded.month,
            description=excluded.description,
            amount=excluded.amount,
            type=excluded.type,
            category=excluded.category,
            sub_category=excluded.sub_category,
            account_name=excluded.account_name,
            transfer_target=excluded.transfer_target,
            is_transfer=excluded.is_transfer,
            is_excluded=excluded.is_excluded,
            scraped_at=excluded.scraped_at
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def insert_holdings_snapshot(
    conn: sqlite3.Connection, snapshot_date: str, items: list[dict]
) -> int:
    """
    その時点の資産(銘柄別)をスナップショットとして保存する。
    実行するたびに新しいスナップショットが追加されるので、時系列の推移を見られる。
    """
    scraped_at = _now_iso()
    rows = [
        (
            snapshot_date,
            item["type"],
            item["name"],
            item.get("code"),
            item.get("institution"),
            item.get("quantity"),
            item.get("avg_cost_price"),
            item.get("unit_price"),
            item["balance"],
            item.get("daily_change"),
            item.get("unrealized_gain"),
            item.get("unrealized_gain_pct"),
            scraped_at,
        )
        for item in items
    ]

    conn.executemany(
        """
        INSERT INTO holdings_snapshots (
            snapshot_date, type, name, code, institution,
            quantity, avg_cost_price, unit_price, balance,
            daily_change, unrealized_gain, unrealized_gain_pct, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)
