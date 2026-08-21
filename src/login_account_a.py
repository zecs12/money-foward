"""
アカウントA(楽天銀行・楽天証券をひもづけているマネーフォワードMEアカウント)に
自動ログインし、成功したことを画面(スクリーンショット)で確認するスクリプト。

使い方:
    python src/login_account_a.py

初回は .env の MF_HEADLESS=false にして、ブラウザ画面を表示しながら
正しく動くか目で確認することをおすすめします。
2段階認証(ワンタイムコード)が求められた場合は、ターミナルの指示に従って
届いたコードを入力してください(自動取得はしません)。

ログインに成功すると、次回以降ログインをスキップできるように
セッション情報を data/account_a_auth_state.json に保存します。
"""

from playwright.sync_api import sync_playwright

from config import DATA_DIR, get_account_a_credentials
from mf_session import open_authenticated_session


def main() -> None:
    credentials = get_account_a_credentials()

    with sync_playwright() as playwright:
        session = open_authenticated_session(playwright, credentials)

        screenshot_path = DATA_DIR / "account_a_login_result.png"
        session.page.screenshot(path=str(screenshot_path))
        print(f"確認用のスクリーンショットを保存しました: {screenshot_path}")

        session.close()


if __name__ == "__main__":
    main()
