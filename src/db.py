"""
取得したデータを保存するローカルデータベース(SQLite)まわりの処理。

SQLiteは、専用のサーバーを用意しなくても使える「ファイル1つのデータベース」。
このファイルは data/money.db に保存される(Gitには含めない)。
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR
from text_match import normalize_text

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

CREATE TABLE IF NOT EXISTS card_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_name TEXT NOT NULL,
    statement_payment_date TEXT NOT NULL,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount INTEGER NOT NULL,
    payment_type TEXT,
    family_member TEXT,
    note TEXT,
    source_file TEXT,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE,
    keyword_normalized TEXT NOT NULL,
    major_category TEXT NOT NULL,
    minor_category TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    major_category TEXT NOT NULL,
    minor_category TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(major_category, minor_category)
);

CREATE INDEX IF NOT EXISTS idx_transactions_month ON transactions(month);
CREATE INDEX IF NOT EXISTS idx_holdings_snapshot_date ON holdings_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_card_transactions_date ON card_transactions(date);
CREATE INDEX IF NOT EXISTS idx_card_transactions_payment_date ON card_transactions(statement_payment_date);
CREATE INDEX IF NOT EXISTS idx_category_rules_updated_at ON category_rules(updated_at);
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


def replace_card_transactions(
    conn: sqlite3.Connection,
    card_name: str,
    statement_payment_date: str,
    rows: list[dict],
    source_file: str | None = None,
) -> int:
    """
    セゾンカードの明細を保存する。同じカード・同じお支払日のデータが既にあれば、
    いったん削除してから入れ直す(1枚のCSV=1回のご請求分、という単位のため、
    同じCSVを読み込み直しても重複登録にならない)。
    """
    imported_at = _now_iso()
    conn.execute(
        "DELETE FROM card_transactions WHERE card_name = ? AND statement_payment_date = ?",
        (card_name, statement_payment_date),
    )

    insert_rows = [
        (
            card_name,
            statement_payment_date,
            r["date"],
            r["description"],
            r["amount"],
            r.get("payment_type"),
            r.get("family_member"),
            r.get("note"),
            source_file,
            imported_at,
        )
        for r in rows
    ]

    conn.executemany(
        """
        INSERT INTO card_transactions (
            card_name, statement_payment_date, date, description, amount,
            payment_type, family_member, note, source_file, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        insert_rows,
    )
    conn.commit()
    return len(insert_rows)


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


def upsert_category(conn: sqlite3.Connection, major_category: str, minor_category: str | None) -> None:
    """
    「大項目・中項目」の組み合わせを一覧に登録する。既に同じ組み合わせがあれば何もしない。
    カテゴリ分類ルールを保存したときにも、自動的にここへ登録される
    (ルールで新しく使った組み合わせが、次からは一覧から選べるようになる)。
    """
    major_category = major_category.strip()
    minor_category = (minor_category or "").strip()
    if not major_category:
        return
    created_at = _now_iso()

    conn.execute(
        """
        INSERT INTO categories (major_category, minor_category, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(major_category, minor_category) DO NOTHING
        """,
        (major_category, minor_category, created_at),
    )
    conn.commit()


def delete_category(conn: sqlite3.Connection, category_id: int) -> None:
    """
    一覧から「大項目・中項目」の組み合わせを削除する。
    既にこの組み合わせが設定されている明細やルールには影響しない
    (あくまで、これから選ぶときの候補一覧から消えるだけ)。
    """
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()


def update_category(
    conn: sqlite3.Connection, category_id: int, major_category: str, minor_category: str | None
) -> None:
    """
    登録済みの「大項目・中項目」の組み合わせを、新しい名前に書き換える。
    この組み合わせを使っているルールがあれば、そちらも新しい名前に合わせて更新する。
    """
    major_category = major_category.strip()
    minor_category = (minor_category or "").strip()
    if not major_category:
        return

    row = conn.execute(
        "SELECT major_category, minor_category FROM categories WHERE id = ?", (category_id,)
    ).fetchone()
    if row is None:
        return
    old_major, old_minor = row

    try:
        conn.execute(
            "UPDATE categories SET major_category = ?, minor_category = ? WHERE id = ?",
            (major_category, minor_category, category_id),
        )
    except sqlite3.IntegrityError:
        # 変更後の組み合わせが既に別の行として登録済みだった場合は、
        # 今の行を消して、既存の行のほうを使う(登録済み一覧が重複しないようにする)
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    updated_at = _now_iso()
    if old_minor:
        conn.execute(
            """
            UPDATE category_rules SET major_category = ?, minor_category = ?, updated_at = ?
            WHERE major_category = ? AND minor_category = ?
            """,
            (major_category, minor_category or None, updated_at, old_major, old_minor),
        )
    else:
        conn.execute(
            """
            UPDATE category_rules SET major_category = ?, minor_category = ?, updated_at = ?
            WHERE major_category = ? AND (minor_category IS NULL OR minor_category = '')
            """,
            (major_category, minor_category or None, updated_at, old_major),
        )
    conn.commit()


def upsert_category_rule(
    conn: sqlite3.Connection,
    keyword: str,
    major_category: str,
    minor_category: str | None,
    register_category: bool = True,
) -> None:
    """
    カテゴリ分類ルールを保存する。同じキーワードのルールが既にあれば、
    内容(大項目・中項目)を上書きし、更新日時も最新にする
    (優先順位は「一番最近登録・変更したルール」が勝つ仕組みのため)。

    register_category=True の場合、使った大項目・中項目の組み合わせを
    一覧(categories)にも登録する。明細一覧の表からの編集のように、
    大項目・中項目が1つずつ別々に確定していく(=まだ組み合わせが
    確定していない途中の状態を経由する)呼び出し元では、途中の組み合わせが
    一覧に紛れ込まないよう、False を指定してもらう。
    """
    keyword = keyword.strip()
    keyword_normalized = normalize_text(keyword)
    updated_at = _now_iso()

    conn.execute(
        """
        INSERT INTO category_rules (keyword, keyword_normalized, major_category, minor_category, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(keyword) DO UPDATE SET
            keyword_normalized=excluded.keyword_normalized,
            major_category=excluded.major_category,
            minor_category=excluded.minor_category,
            updated_at=excluded.updated_at
        """,
        (keyword, keyword_normalized, major_category, minor_category or None, updated_at),
    )
    conn.commit()
    if register_category:
        upsert_category(conn, major_category, minor_category)


def delete_category_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    """
    カテゴリ分類ルールを削除する。このルールで分類されていた明細は、
    他に一致するルールが無ければ「未分類」に戻る
    (明細に直接カテゴリを保存せず、その都度ルールと照らし合わせて決めているため)。
    """
    conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    conn.commit()
