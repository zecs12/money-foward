"""
アカウントA(楽天銀行・楽天証券をひもづけているマネーフォワードMEアカウント)に
自動ログインするスクリプト。

使い方:
    python src/login_account_a.py

初回は .env の MF_HEADLESS=false にして、ブラウザ画面を表示しながら
正しく動くか目で確認することをおすすめします。
2段階認証(ワンタイムコード)が求められた場合は、ターミナルの指示に従って
届いたコードを入力してください(自動取得はしません)。

ログインに成功すると、次回以降ログインをスキップできるように
セッション情報を data/account_a_auth_state.json に保存します。
"""

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from config import AUTH_STATE_PATH, DATA_DIR, get_account_a_credentials, is_headless

MF_ID_SIGN_IN_URL = "https://id.moneyforward.com/sign_in"
MF_SIGN_IN_URL = "https://moneyforward.com/sign_in"
MF_ACCOUNTS_URL = "https://moneyforward.com/accounts"

# mf-dashboard (https://github.com/hiroppy/mf-dashboard) のログイン処理を参考にしたセレクタ
SELECTORS = {
    "mfid_email": 'input[name="mfid_user[email]"]',
    "mfid_password": 'input[name="mfid_user[password]"]',
    "mfid_submit": "#submitto",
    "mfid_otp_input": 'input[autocomplete="one-time-code"], input[name*="otp"], input[name*="code"]',
    "mfid_otp_submit": '#submitto, button:text-is("認証する"), button:text-is("Verify")',
    "me_password": 'input[type="password"]',
    "me_sign_in": 'button:has-text("Sign in")',
}

TIMEOUT_MEDIUM = 10_000
TIMEOUT_LONG = 15_000
TIMEOUT_LOGIN = 30_000
TIMEOUT_OTP_CHECK = 5_000


def is_logged_in_url(url: str) -> bool:
    return url.startswith(MF_ACCOUNTS_URL)


def maybe_handle_otp(page: Page) -> None:
    """2段階認証(ワンタイムコード)の入力欄が出てきた場合、ターミナルで入力してもらう。"""
    otp_input = page.locator(SELECTORS["mfid_otp_input"]).first
    try:
        otp_input.wait_for(state="visible", timeout=TIMEOUT_OTP_CHECK)
    except PlaywrightTimeoutError:
        # 入力欄が出てこない = 2段階認証は不要だったということ
        return

    print("2段階認証が求められました。マネーフォワードMEから届いたコードを入力してください。")
    code = input("ワンタイムコード: ").strip()
    otp_input.fill(code)
    page.locator(SELECTORS["mfid_otp_submit"]).first.click()


def login(page: Page, email: str, password: str) -> None:
    print("ログインページを開いています...")
    page.goto(MF_ID_SIGN_IN_URL, wait_until="domcontentloaded")

    print("メールアドレスを入力しています...")
    email_input = page.locator(SELECTORS["mfid_email"])
    email_input.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
    email_input.fill(email)
    page.locator(SELECTORS["mfid_submit"]).click()

    print("パスワードを入力しています...")
    password_input = page.locator(SELECTORS["mfid_password"])
    password_input.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
    password_input.fill(password)
    page.locator(SELECTORS["mfid_submit"]).click()

    maybe_handle_otp(page)

    print("ログイン完了を待っています...")
    page.wait_for_url(lambda url: "moneyforward.com" in url, timeout=TIMEOUT_LOGIN)

    # マネーフォワードME側にも遷移して、ログイン状態を確定させる
    # (サイトによってはアカウント選択・パスワード再入力が挟まる)
    page.goto(MF_SIGN_IN_URL)
    page.wait_for_timeout(2000)

    current_url = page.url
    if "account_selector" in current_url:
        print("アカウント選択画面が表示されました。アカウントを選択しています...")
        account_button = page.locator(
            f'button:has-text("{email}"), button:has-text("メールアドレスでログイン")'
        ).first
        account_button.wait_for(state="visible", timeout=TIMEOUT_LONG)
        account_button.click()
        page.wait_for_timeout(2000)
        current_url = page.url

    if "sign_in/password" in current_url:
        print("マネーフォワードME側でもう一度パスワードを入力しています...")
        me_password_input = page.locator(SELECTORS["me_password"]).first
        me_password_input.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
        me_password_input.fill(password)
        page.locator(SELECTORS["me_sign_in"]).click()
        page.wait_for_url(f"{MF_SIGN_IN_URL}**", timeout=TIMEOUT_LOGIN)

    # 会員限定ページ(口座一覧)に実際に到達できるかどうかで、ログイン成功を確認する
    # (トップページは非ログインでも見えるため、確認には使えない)
    print("ログインが成功したか確認しています...")
    page.goto(MF_ACCOUNTS_URL)
    page.wait_for_timeout(2000)

    if not is_logged_in_url(page.url):
        raise RuntimeError(
            f"ログインに失敗しました(想定外のページに遷移しています: {page.url})。"
            " 画面を確認するか、メールアドレス・パスワードが正しいか見直してください。"
        )

    print("ログインに成功しました!")


def main() -> None:
    credentials = get_account_a_credentials()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=is_headless())

        storage_state = str(AUTH_STATE_PATH) if AUTH_STATE_PATH.exists() else None
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()

        session_is_valid = False
        if storage_state:
            print("保存済みのログイン情報があります。有効か確認しています...")
            page.goto(MF_ACCOUNTS_URL)
            page.wait_for_timeout(2000)
            session_is_valid = is_logged_in_url(page.url)

        if session_is_valid:
            print("保存済みのログイン情報が有効だったので、ログイン処理をスキップしました。")
        else:
            login(page, credentials.email, credentials.password)
            context.storage_state(path=str(AUTH_STATE_PATH))
            print(f"ログイン情報を保存しました: {AUTH_STATE_PATH}")

        screenshot_path = DATA_DIR / "account_a_login_result.png"
        page.screenshot(path=str(screenshot_path))
        print(f"確認用のスクリーンショットを保存しました: {screenshot_path}")

        browser.close()


if __name__ == "__main__":
    main()
