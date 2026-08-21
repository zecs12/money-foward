"""
セゾンカードの利用明細CSVを読み込み、ローカルデータベース(data/money.db)に
取り込むスクリプト。

セゾンカードの利用明細は自動取得(スクレイピング)ではなく、以下の手順で
手動でダウンロードしてから、このスクリプトで取り込む方式です。

使い方:
    1. セゾンカードの会員サイトから、該当月の利用明細CSVをダウンロードする
    2. ダウンロードしたCSVファイルを data/saison_csv フォルダに入れる
       (このフォルダが無ければ、このスクリプトを一度実行すると自動的に作られます)
    3. ターミナルで以下を実行する

        python src/import_saison_csv.py

    data/saison_csv フォルダの中にある .csv ファイルをすべて読み込みます。
    1つのファイルだけを指定したい場合は、以下のように実行することもできます。

        python src/import_saison_csv.py "ファイルのパス.csv"

同じ「カード名称」「お支払日」の組み合わせのCSVを読み込み直しても、
古いデータが入れ替わるだけで、重複して増えることはありません。

CSVの形式(セゾンカードの会員サイトでダウンロードできる標準的な明細CSV):
    1行目: カード名称,○○○○
    2行目: お支払日,YYYY/MM/DD
    3行目: 今回ご請求額,0000000000
    4行目: (空行)
    5行目: 利用日,ご利用店名及び商品名,本人・家族区分,支払区分名称,締前入金区分,利用金額,備考
    6行目以降: 明細データ
"""

import csv
import sys
from pathlib import Path

from config import DATA_DIR
from db import get_connection, replace_card_transactions

SAISON_CSV_DIR = DATA_DIR / "saison_csv"

# セゾンカードのCSVは、Windowsで使われる日本語の文字コード(cp932)で
# 保存されていることが多い。念のため、いくつかの文字コードを順番に試す。
ENCODING_CANDIDATES = ["cp932", "shift_jis", "utf-8-sig", "utf-8"]

HEADER_ROW_PREFIX = "利用日,"
CARD_NAME_PREFIX = "カード名称,"
PAYMENT_DATE_PREFIX = "お支払日,"


def _read_text(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as error:
            last_error = error
    raise ValueError(
        f"{path.name}: 文字コードを判定できませんでした"
        f"({', '.join(ENCODING_CANDIDATES)} のいずれでも読み込めませんでした)"
    ) from last_error


def parse_saison_csv(path: Path) -> tuple[str, str, list[dict]]:
    """CSVファイルを読み込み、(カード名称, お支払日, 明細データのリスト) を返す。"""
    lines = _read_text(path).splitlines()

    card_name: str | None = None
    payment_date: str | None = None
    header_index: int | None = None

    for i, line in enumerate(lines):
        if line.startswith(CARD_NAME_PREFIX):
            card_name = line.split(",", 1)[1].strip()
        elif line.startswith(PAYMENT_DATE_PREFIX):
            payment_date = line.split(",", 1)[1].strip().replace("/", "-")
        elif line.startswith(HEADER_ROW_PREFIX):
            header_index = i
            break

    if header_index is None:
        raise ValueError(f"{path.name}: 明細の見出し行(「利用日,...」)が見つかりませんでした")
    if not card_name:
        raise ValueError(f"{path.name}: 「カード名称」の行が見つかりませんでした")
    if not payment_date:
        raise ValueError(f"{path.name}: 「お支払日」の行が見つかりませんでした")

    reader = csv.DictReader(lines[header_index:])
    rows = []
    for row in reader:
        date_text = (row.get("利用日") or "").strip()
        if not date_text:
            # 空行や、合計行など、明細ではない行はスキップする
            continue

        amount_text = (row.get("利用金額") or "0").strip().replace(",", "")
        rows.append(
            {
                "date": date_text.replace("/", "-"),
                "description": (row.get("ご利用店名及び商品名") or "").strip(),
                "amount": int(amount_text) if amount_text else 0,
                "payment_type": (row.get("支払区分名称") or "").strip() or None,
                "family_member": (row.get("本人・家族区分") or "").strip() or None,
                "note": (row.get("備考") or "").strip() or None,
            }
        )

    return card_name, payment_date, rows


def _collect_csv_files(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(target.glob("*.csv"))
    if target.is_file():
        return [target]
    return []


def main() -> None:
    SAISON_CSV_DIR.mkdir(parents=True, exist_ok=True)

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else SAISON_CSV_DIR
    csv_files = _collect_csv_files(target)

    if not csv_files:
        print(f"{target} の中にCSVファイルが見つかりませんでした。")
        print(
            "セゾンカードの会員サイトからダウンロードしたCSVファイルを "
            f"{SAISON_CSV_DIR} フォルダに置いてから、もう一度実行してください。"
        )
        return

    conn = get_connection()
    total_saved = 0

    for path in csv_files:
        try:
            card_name, payment_date, rows = parse_saison_csv(path)
        except ValueError as error:
            print(f"読み込みに失敗しました: {error}")
            continue

        saved = replace_card_transactions(
            conn, card_name, payment_date, rows, source_file=path.name
        )
        print(f"{path.name}: 「{card_name}」お支払日 {payment_date} の明細 {saved}件を保存しました")
        total_saved += saved

    print(f"合計 {total_saved} 件をデータベースに保存しました。")


if __name__ == "__main__":
    main()
