""".env ファイルから設定値を読み込むモジュール。"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# リポジトリ直下の .env を読み込む
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUTH_STATE_PATH = DATA_DIR / "account_a_auth_state.json"


@dataclass
class Credentials:
    email: str
    password: str


def get_account_a_credentials() -> Credentials:
    email = os.environ.get("MF_ACCOUNT_A_EMAIL", "").strip()
    password = os.environ.get("MF_ACCOUNT_A_PASSWORD", "").strip()

    if not email or not password:
        raise RuntimeError(
            "MF_ACCOUNT_A_EMAIL / MF_ACCOUNT_A_PASSWORD が .env に設定されていません。"
            " .env.example を .env にコピーして値を入力してください。"
        )

    return Credentials(email=email, password=password)


def is_headless() -> bool:
    return os.environ.get("MF_HEADLESS", "false").strip().lower() == "true"
