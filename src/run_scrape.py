"""
アカウントAに1回だけログインし、
・楽天銀行の明細(家計簿)
・楽天証券のNISA状況(資産スナップショット)
の両方をまとめて取得するスクリプト。

使い方:
    python src/run_scrape.py --full     # 初回: 明細は全期間、資産は最新時点を取得
    python src/run_scrape.py             # 通常: 明細は直近3か月、資産は最新時点を取得
"""

import argparse
from datetime import date

from playwright.sync_api import sync_playwright

from config import get_account_a_credentials
from db import DB_PATH, get_connection, insert_holdings_snapshot, upsert_transactions
from mf_session import open_authenticated_session
from scrape_cash_flow import scrape_cash_flow
from scrape_portfolio import scrape_portfolio


def main() -> None:
    parser = argparse.ArgumentParser(
        description="楽天銀行の明細と楽天証券の資産状況をまとめて取得します"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="明細を登録されている全期間分取得します(初回の実行におすすめです)",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        help="明細を取得する月数。--full を指定しない場合に有効(既定値: 3か月分)",
    )
    args = parser.parse_args()

    credentials = get_account_a_credentials()
    conn = get_connection()

    with sync_playwright() as playwright:
        session = open_authenticated_session(playwright, credentials)

        months = None if args.full else args.months
        transactions = scrape_cash_flow(session.page, months)

        holdings = scrape_portfolio(session.page)

        session.close()

    saved_transactions = upsert_transactions(conn, transactions)
    print(f"{saved_transactions} 件の明細をデータベースに保存しました。")

    snapshot_date = date.today().isoformat()
    saved_holdings = insert_holdings_snapshot(conn, snapshot_date, holdings)
    print(f"{saved_holdings} 件の資産データを {snapshot_date} 時点のスナップショットとして保存しました。")

    print(f"データベース: {DB_PATH}")


if __name__ == "__main__":
    main()
