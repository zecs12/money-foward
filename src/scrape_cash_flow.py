"""
楽天銀行(および楽天証券)の明細を、マネーフォワードMEの「家計簿」ページから取得し、
ローカルデータベース(data/money.db)に保存するスクリプト。

使い方:
    python src/scrape_cash_flow.py --full       # 初回: 登録されている全期間の明細を取得
    python src/scrape_cash_flow.py               # 通常: 直近3か月分だけ取得(差分更新用)
    python src/scrape_cash_flow.py --months 6     # 直近6か月分だけ取得

同じ明細(取引)を何度取得しても、内部のID(mf_id)で上書き保存されるだけなので、
重複してデータが増えることはない。
"""

import argparse
import re

from playwright.sync_api import Locator, Page, sync_playwright

from config import get_account_a_credentials
from db import DB_PATH, get_connection, upsert_transactions
from mf_session import open_authenticated_session
from parsers import convert_date_to_iso, parse_japanese_number

CASH_FLOW_URL = "https://moneyforward.com/cf"

# #cf-detail-table の列番号: 計算対象|日付|内容|金額|保有金融機関|大項目|中項目|メモ|振替|削除
COLUMNS = {
    "DATE": 1,
    "DESCRIPTION": 2,
    "AMOUNT": 3,
    "ACCOUNT": 4,
    "CATEGORY": 5,
    "SUB_CATEGORY": 6,
}

TIMEOUT_LONG = 15_000
# これ以上さかのぼらない、という安全のための上限(10年分)
MAX_HISTORY_MONTHS = 120

_CSV_YEAR_PATTERN = re.compile(r"[?&]year=(\d{4})")
_CSV_MONTH_PATTERN = re.compile(r"[?&]month=(\d{1,2})")
_HEADER_MONTH_PATTERN = re.compile(r"(\d{4})年(\d{1,2})月")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(locator: Locator) -> str:
    return (locator.text_content() or "").strip()


def _detect_month(page: Page) -> tuple[str, int]:
    """現在表示中の年月を「YYYY-MM」の形で検出する。"""
    csv_link = page.locator("a[href*='/cf/csv']").first
    if csv_link.count() > 0:
        href = csv_link.get_attribute("href") or ""
        year_match = _CSV_YEAR_PATTERN.search(href)
        month_match = _CSV_MONTH_PATTERN.search(href)
        if year_match and month_match:
            year, month = int(year_match.group(1)), int(month_match.group(1))
            return f"{year}-{month:02d}", year

    header = page.locator(".fc-header-title h2").first
    header_text = _text(header) if header.count() > 0 else ""
    match = _HEADER_MONTH_PATTERN.search(header_text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        return f"{year}-{month:02d}", year

    raise RuntimeError(
        "表示中の年月を検出できませんでした。マネーフォワードME側の画面構成が"
        "変わった可能性があります。"
    )


def _parse_account_cell(cell: Locator) -> tuple[str | None, str | None]:
    """振替(口座間の資金移動)の場合、送金元・送金先を分けて取り出す。"""
    transfer_box = cell.locator(".transfer_account_box")
    if transfer_box.count() > 0:
        full_text = _text(cell)
        to_text = _text(transfer_box.first)
        from_text = full_text.replace(to_text, "").strip()
        return (from_text or None, to_text or None)

    noform_span = cell.locator("div.noform span")
    text = _text(noform_span.first) if noform_span.count() > 0 else _text(cell)
    return (text or None, None)


def _detect_type(amount_cell: Locator, category_text: str) -> str:
    if category_text == "":
        return "transfer"

    class_attr = amount_cell.get_attribute("class") or ""
    style_attr = amount_cell.get_attribute("style") or ""
    html = amount_cell.inner_html()

    is_income = (
        "plus" in class_attr
        or "income" in class_attr
        or "blue" in class_attr
        or "blue" in style_attr
        or "plus" in html
        or ("color" in html and "blue" in html)
    )
    return "income" if is_income else "expense"


def _parse_row(row: Locator, year: int) -> dict | None:
    row_id = row.get_attribute("id") or ""
    if not row_id.startswith("js-transaction-"):
        return None
    mf_id = row_id[len("js-transaction-") :]

    row_class = row.get_attribute("class") or ""
    cells = row.locator("td")

    date_text = _text(cells.nth(COLUMNS["DATE"]))
    description = _text(cells.nth(COLUMNS["DESCRIPTION"]))
    amount_text = _text(cells.nth(COLUMNS["AMOUNT"]))
    category_text = _text(cells.nth(COLUMNS["CATEGORY"]))
    sub_category_text = _text(cells.nth(COLUMNS["SUB_CATEGORY"]))

    date = convert_date_to_iso(date_text, year)
    if not _ISO_DATE_PATTERN.match(date):
        return None

    account_from, account_to = _parse_account_cell(cells.nth(COLUMNS["ACCOUNT"]))
    is_excluded = "mf-grayout" in row_class

    tx_type = _detect_type(cells.nth(COLUMNS["AMOUNT"]), category_text)
    is_transfer = tx_type == "transfer"

    account_name: str | None = None
    transfer_target: str | None = None
    if account_to:
        account_name = account_to
        transfer_target = account_from
    elif is_transfer and account_from and "口座" not in account_from:
        transfer_target = account_from
    elif account_from:
        account_name = account_from

    return {
        "mf_id": mf_id,
        "date": date,
        "description": description,
        "amount": abs(parse_japanese_number(amount_text)),
        "type": tx_type,
        "category": category_text or None,
        "sub_category": sub_category_text or None,
        "account_name": account_name,
        "transfer_target": transfer_target,
        "is_transfer": is_transfer,
        "is_excluded": is_excluded,
    }


def _extract_transactions(page: Page, year: int) -> list[dict]:
    rows = page.locator("#cf-detail-table tbody > tr")
    items = []
    for i in range(rows.count()):
        item = _parse_row(rows.nth(i), year)
        if item:
            items.append(item)
    return items


def _go_to_prev_month(page: Page) -> bool:
    """前の月の画面に移動する。移動できればTrue、これ以上過去がなければFalse。"""
    current_month, _ = _detect_month(page)
    prev_button = page.locator("button.fc-button-prev, span.fc-button-prev").first
    if prev_button.count() == 0:
        return False

    with page.expect_response(
        lambda res: "/cf/fetch" in res.url and res.status == 200, timeout=TIMEOUT_LONG
    ):
        prev_button.click()
    page.wait_for_timeout(500)

    new_month, _ = _detect_month(page)
    return new_month != current_month


def scrape_cash_flow(page: Page, months: int | None) -> list[dict]:
    """
    家計簿(明細)を取得する。
    months に None を渡すと、これ以上過去のデータがなくなるまで(全期間)取得する。
    """
    print("家計簿ページを開いています...")
    page.goto(CASH_FLOW_URL, wait_until="domcontentloaded")
    page.locator("#cf-detail-table").wait_for(state="visible", timeout=TIMEOUT_LONG)

    max_months = months if months is not None else MAX_HISTORY_MONTHS
    all_items: list[dict] = []
    scraped = 0

    while scraped < max_months:
        month, year = _detect_month(page)
        print(f"{month} の明細を取得しています...")
        items = _extract_transactions(page, year)
        print(f"  {len(items)} 件見つかりました")
        all_items.extend(items)
        scraped += 1

        if scraped >= max_months:
            break

        if not _go_to_prev_month(page):
            print("これより過去のデータはありませんでした。")
            break

    return all_items


def main() -> None:
    parser = argparse.ArgumentParser(description="楽天銀行の明細(家計簿)を取得します")
    parser.add_argument(
        "--full",
        action="store_true",
        help="登録されている全期間の明細を取得します(初回の実行におすすめです)",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        help="取得する月数。--full を指定しない場合に有効(既定値: 3か月分)",
    )
    args = parser.parse_args()

    credentials = get_account_a_credentials()
    conn = get_connection()

    with sync_playwright() as playwright:
        session = open_authenticated_session(playwright, credentials)
        months = None if args.full else args.months
        transactions = scrape_cash_flow(session.page, months)
        session.close()

    saved = upsert_transactions(conn, transactions)
    print(f"{saved} 件の明細をデータベースに保存しました: {DB_PATH}")


if __name__ == "__main__":
    main()
