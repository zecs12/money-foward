"""
楽天証券のNISA状況(保有銘柄ごとの内訳)を、マネーフォワードMEの
「資産管理 > ポートフォリオ」ページから取得し、ローカルデータベース
(data/money.db)にスナップショットとして保存するスクリプト。

使い方:
    python src/scrape_portfolio.py

実行するたびに、その時点の保有状況が新しいスナップショットとして
追加される(上書きではない)ので、資産の推移をあとから見返せる。
預金(楽天銀行の残高)・株式・投資信託(NISAの投資信託はここに含まれる)を
まとめて取得する。
"""

from datetime import date

from playwright.sync_api import Locator, Page, sync_playwright

from config import get_account_a_credentials
from db import DB_PATH, get_connection, insert_holdings_snapshot
from mf_session import open_authenticated_session
from parsers import parse_decimal_number, parse_japanese_number, parse_optional_japanese_number, parse_percentage

PORTFOLIO_URL = "https://moneyforward.com/bs/portfolio"
TIMEOUT_LONG = 15_000

DEPOSIT_COLUMNS = {"NAME": 0, "BALANCE": 1, "INSTITUTION": 2}
STOCK_COLUMNS = {
    "CODE": 0,
    "NAME": 1,
    "QUANTITY": 2,
    "AVG_COST": 3,
    "UNIT_PRICE": 4,
    "BALANCE": 5,
    "DAILY_CHANGE": 6,
    "UNREALIZED_GAIN": 7,
    "UNREALIZED_GAIN_PCT": 8,
    "INSTITUTION": 9,
}
FUND_COLUMNS = {
    "NAME": 0,
    "QUANTITY": 1,
    "AVG_COST": 2,
    "UNIT_PRICE": 3,
    "BALANCE": 4,
    "DAILY_CHANGE": 5,
    "UNREALIZED_GAIN": 6,
    "UNREALIZED_GAIN_PCT": 7,
    "INSTITUTION": 8,
}


def _cell_text(cells: Locator, index: int) -> str:
    return (cells.nth(index).text_content() or "").strip()


def _institution_text(cells: Locator, index: int) -> str:
    cell = cells.nth(index)
    link = cell.locator("a").first
    if link.count() > 0:
        return (link.text_content() or "").strip()
    return (cell.text_content() or "").strip()


def _parse_deposits(page: Page) -> list[dict]:
    tables = page.locator("table.table-depo")
    items = []
    for t in range(tables.count()):
        rows = tables.nth(t).locator("tbody tr")
        for i in range(rows.count()):
            cells = rows.nth(i).locator("td")
            name = _cell_text(cells, DEPOSIT_COLUMNS["NAME"])
            if not name:
                continue
            items.append(
                {
                    "type": "預金・現金",
                    "name": name,
                    "institution": _institution_text(cells, DEPOSIT_COLUMNS["INSTITUTION"]),
                    "balance": parse_japanese_number(
                        _cell_text(cells, DEPOSIT_COLUMNS["BALANCE"]) or "0"
                    ),
                }
            )
    return items


def _parse_investment_rows(page: Page, table_selector: str, columns: dict, item_type: str) -> list[dict]:
    rows = page.locator(f"{table_selector} tbody tr")
    items = []
    for i in range(rows.count()):
        cells = rows.nth(i).locator("td")
        name = _cell_text(cells, columns["NAME"])
        if not name:
            continue

        item = {
            "type": item_type,
            "name": name,
            "institution": _institution_text(cells, columns["INSTITUTION"]),
            "balance": parse_japanese_number(_cell_text(cells, columns["BALANCE"]) or "0"),
            "quantity": parse_decimal_number(_cell_text(cells, columns["QUANTITY"])) or None,
            "avg_cost_price": parse_decimal_number(_cell_text(cells, columns["AVG_COST"])) or None,
            "unit_price": parse_decimal_number(_cell_text(cells, columns["UNIT_PRICE"])) or None,
            "daily_change": parse_optional_japanese_number(_cell_text(cells, columns["DAILY_CHANGE"])),
            "unrealized_gain": parse_optional_japanese_number(
                _cell_text(cells, columns["UNREALIZED_GAIN"])
            ),
            "unrealized_gain_pct": parse_percentage(
                _cell_text(cells, columns["UNREALIZED_GAIN_PCT"])
            ),
        }
        if "CODE" in columns:
            item["code"] = _cell_text(cells, columns["CODE"]) or None
        items.append(item)
    return items


def scrape_portfolio(page: Page) -> list[dict]:
    print("資産(ポートフォリオ)ページを開いています...")
    page.goto(PORTFOLIO_URL, wait_until="domcontentloaded")
    page.locator("h1.heading-normal").first.wait_for(state="visible", timeout=TIMEOUT_LONG)

    deposits = _parse_deposits(page)
    stocks = _parse_investment_rows(page, "table.table-eq", STOCK_COLUMNS, "株式(現物)")
    funds = _parse_investment_rows(page, "table.table-mf", FUND_COLUMNS, "投資信託")

    print(f"  預金・現金: {len(deposits)}件 / 株式: {len(stocks)}件 / 投資信託: {len(funds)}件")
    return [*deposits, *stocks, *funds]


def main() -> None:
    credentials = get_account_a_credentials()
    conn = get_connection()

    with sync_playwright() as playwright:
        session = open_authenticated_session(playwright, credentials)
        items = scrape_portfolio(session.page)
        session.close()

    snapshot_date = date.today().isoformat()
    saved = insert_holdings_snapshot(conn, snapshot_date, items)
    print(f"{saved} 件の資産データを {snapshot_date} 時点のスナップショットとして保存しました: {DB_PATH}")


if __name__ == "__main__":
    main()
