"""
文字列の表記ゆれを吸収して比較するための共通処理。

例えば「全角/半角」や、見た目が似ている「伸ばす記号」
(ー:音引き、－:全角ハイフン、-:半角ハイフン、−:マイナス記号 など)の違いを
無視して、同じキーワードとして扱えるようにする。
"""

import re
import unicodedata

# 「伸ばす記号」として同一視する文字。カタカナの音引き(ー)や全角ハイフン(－)は
# unicodedata.normalize だけでは半角ハイフンに統一されないため、個別に置き換える。
_DASH_LIKE_PATTERN = re.compile("[-‐‑‒–—―−ー－]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """
    比較用に正規化した文字列を返す。
    全角英数字は半角に、大文字は小文字に、伸ばす記号はすべて「-」に統一する。
    """
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKC", text)
    normalized = _DASH_LIKE_PATTERN.sub("-", normalized)
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized)
    return normalized.strip().lower()
