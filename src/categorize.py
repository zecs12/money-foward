"""
明細の「内容」と、登録済みのカテゴリ分類ルールを照らし合わせて、
大項目・中項目を決める処理。

- 判定は、明細の「内容」にルールの「キーワード」が含まれているか(部分一致)で行う
  (全角/半角、伸ばす記号の違いは text_match.normalize_text で吸収する)
- 複数のルールが一致した場合は、一番最近登録・変更したルールを優先する
- どのルールにも一致しない場合は「未分類」になる
- 明細そのものにはカテゴリを保存せず、表示するたびにルールと照らし合わせて
  その場で決めている。そのためルールを追加・変更・削除すると、対象の明細の
  表示にすぐ反映される。
"""

import pandas as pd

from text_match import normalize_text

UNCATEGORIZED = "未分類"


def apply_category_rules(descriptions: pd.Series, rules_df: pd.DataFrame) -> pd.DataFrame:
    """
    明細の「内容」の列(Series)を受け取り、大項目・中項目の列を持つ
    DataFrame(同じ index)を返す。
    """
    if descriptions.empty:
        return pd.DataFrame(
            {"major_category": pd.Series(dtype="object"), "minor_category": pd.Series(dtype="object")},
            index=descriptions.index,
        )

    if rules_df.empty:
        return pd.DataFrame(
            {
                "major_category": [UNCATEGORIZED] * len(descriptions),
                "minor_category": [None] * len(descriptions),
            },
            index=descriptions.index,
        )

    # 更新日時が新しいルールほど優先されるよう、先頭に来るよう並べ替える
    rules_sorted = rules_df.sort_values("updated_at", ascending=False)
    rules = list(
        zip(
            rules_sorted["keyword_normalized"],
            rules_sorted["major_category"],
            rules_sorted["minor_category"],
        )
    )

    def match_one(normalized_description: str) -> tuple[str, str | None]:
        for keyword, major, minor in rules:
            if keyword and keyword in normalized_description:
                return major, minor
        return UNCATEGORIZED, None

    # 同じ「内容」の明細は何度も登場するため、重複を除いてから判定することで
    # ルールとの照合回数を減らしている
    unique_descriptions = descriptions.dropna().unique()
    match_cache = {desc: match_one(normalize_text(desc)) for desc in unique_descriptions}

    def lookup(desc: object) -> tuple[str, str | None]:
        return match_cache.get(desc, (UNCATEGORIZED, None))

    majors = descriptions.map(lambda d: lookup(d)[0])
    minors = descriptions.map(lambda d: lookup(d)[1])
    return pd.DataFrame({"major_category": majors, "minor_category": minors}, index=descriptions.index)
