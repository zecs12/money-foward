"""
取得した家計データ(楽天銀行の明細・楽天証券のNISA資産)を、自分のパソコンの中だけで
見るためのダッシュボード。

使い方:
    streamlit run app.py

コマンドを実行すると、自動的にブラウザが開いて画面が表示されます
(http://localhost:8501)。インターネットには公開されず、自分のパソコンの
中だけで完結します。

設計の考え方:
- 楽天銀行(明細・家計簿)と楽天証券(NISA資産)は、別のタブに分けて表示する
  (合計金額を足し合わせて1つの数字にはしない)。
- 銀行の預金残高は、参考としてタブ内に表示するが、NISAの評価額とは合算しない。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import matplotlib.colors as mcolors  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from categorize import apply_category_rules  # noqa: E402
from db import (  # noqa: E402
    DB_PATH,
    delete_category,
    delete_category_rule,
    get_connection,
    upsert_category,
    upsert_category_rule,
)
from viz_theme import (  # noqa: E402
    CATEGORICAL_COLORS,
    DIVERGING_NEGATIVE,
    DIVERGING_NEUTRAL,
    DIVERGING_POSITIVE,
    categorical_color,
)

MONTH_LABELS = [f"{m}月" for m in range(1, 13)]

METRIC_LABELS = {
    "balance": "評価額",
    "quantity": "口数・株数",
    "unit_price": "基準価額・単価",
    "avg_cost_price": "取得単価",
    "unrealized_gain": "評価損益",
    "unrealized_gain_pct": "評価損益率(%)",
}
DIVERGING_METRICS = {"unrealized_gain", "unrealized_gain_pct"}

TRANSACTION_TYPE_LABELS = {"income": "収入", "expense": "支出", "transfer": "振替"}

TRANSACTION_COLUMN_LABELS = {
    "date": "日付",
    "description": "内容",
    "amount": "金額",
    "type": "収支",
    "major_category": "大項目",
    "minor_category": "中項目",
    "account_name": "口座",
}

HOLDINGS_COLUMN_LABELS = {
    "type": "種類",
    "name": "銘柄名",
    "code": "コード",
    "institution": "取扱金融機関",
    "quantity": "口数・株数",
    "unit_price": "基準価額・単価",
    "balance": "評価額",
    "unrealized_gain": "評価損益",
    "unrealized_gain_pct": "評価損益率(%)",
}

CARD_COLUMN_LABELS = {
    "date": "日付",
    "card_name": "カード名",
    "description": "内容",
    "amount": "金額",
    "payment_type": "支払区分",
    "family_member": "本人・家族区分",
    "note": "備考",
}


def _diverging_cmap():
    return mcolors.LinearSegmentedColormap.from_list(
        "diverging", [DIVERGING_NEGATIVE, DIVERGING_NEUTRAL, DIVERGING_POSITIVE]
    )


def _sequential_cmap():
    return mcolors.LinearSegmentedColormap.from_list("sequential", ["#fcfcfb", DIVERGING_POSITIVE])


def _safe_abs_max(df: pd.DataFrame) -> float:
    col_min = df.min().min()
    col_max = df.max().max()
    col_min = 0 if pd.isna(col_min) else col_min
    col_max = 0 if pd.isna(col_max) else col_max
    return max(abs(col_min), abs(col_max), 1)


st.set_page_config(page_title="家計データダッシュボード", layout="wide")
st.title("家計データダッシュボード")
st.caption("このページは自分のパソコンの中だけで表示されます(インターネットには公開されません)")

if not DB_PATH.exists():
    st.warning(
        "まだデータがありません。先にターミナルで `python src/run_scrape.py --full` を"
        "実行して、データを取得してください。"
    )
    st.stop()

conn = get_connection()

tab_bank, tab_nisa, tab_saison, tab_settings = st.tabs(
    ["🏦 楽天銀行(家計簿)", "📈 楽天証券(NISA)", "💳 セゾンカード", "⚙️ カテゴリ設定"]
)

categories_df = pd.read_sql_query(
    "SELECT * FROM categories ORDER BY major_category, minor_category", conn
)


def _major_category_options() -> list[str]:
    if categories_df.empty:
        return []
    return sorted(categories_df["major_category"].unique().tolist())


def _minor_category_options(major_category: str) -> list[str]:
    if categories_df.empty:
        return []
    minors = categories_df.loc[categories_df["major_category"] == major_category, "minor_category"]
    return sorted(m for m in minors.unique().tolist() if m)

# ---------------------------------------------------------------------------
# 楽天銀行(家計簿)
# ---------------------------------------------------------------------------
with tab_bank:
    tx = pd.read_sql_query("SELECT * FROM transactions", conn)
    rules_df = pd.read_sql_query("SELECT * FROM category_rules", conn)

    if tx.empty:
        st.info(
            "明細データがまだありません。ターミナルで "
            "`python src/scrape_cash_flow.py --full` を実行してください。"
        )
    else:
        tx["year"] = tx["date"].str[:4]
        tx["month_num"] = tx["date"].str[5:7].astype(int)

        # 大項目・中項目は、マネーフォワードME側の値ではなく、
        # 下の「カテゴリ分類ルール」で自分で決めた内容を使う
        categorized = apply_category_rules(tx["description"], rules_df)
        tx["major_category"] = categorized["major_category"]
        tx["minor_category"] = categorized["minor_category"]

        # 預金残高は参考として表示する(NISAの評価額とは合算しない)
        deposits = pd.read_sql_query(
            "SELECT * FROM holdings_snapshots WHERE type = '預金・現金' "
            "ORDER BY snapshot_date DESC",
            conn,
        )
        if not deposits.empty:
            latest_deposit_date = deposits["snapshot_date"].max()
            latest_deposits = deposits[deposits["snapshot_date"] == latest_deposit_date]
            st.caption(f"預金残高(参考・{latest_deposit_date}時点。NISA資産とは合算していません)")
            dep_cols = st.columns(min(len(latest_deposits), 4))
            for i, (_, row) in enumerate(latest_deposits.iterrows()):
                dep_cols[i % len(dep_cols)].metric(row["name"], f"¥{row['balance']:,.0f}")

        years = sorted(tx["year"].unique(), reverse=True)
        selected_year = st.selectbox("表示する年", years, index=0)

        year_tx = tx[tx["year"] == selected_year]
        target = year_tx[
            (~year_tx["is_transfer"].astype(bool)) & (~year_tx["is_excluded"].astype(bool))
        ].copy()

        income = target[target["type"] == "income"]["amount"].sum()
        expense = target[target["type"] == "expense"]["amount"].sum()

        col1, col2, col3 = st.columns(3)
        col1.metric(f"{selected_year}年の収入", f"¥{income:,.0f}")
        col2.metric(f"{selected_year}年の支出", f"¥{expense:,.0f}")
        col3.metric("収支", f"¥{income - expense:,.0f}")

        if target.empty:
            st.info(f"{selected_year}年の明細データがありません。")
        else:
            target["signed_amount"] = target.apply(
                lambda r: r["amount"] if r["type"] == "income" else -r["amount"], axis=1
            )

            st.subheader(f"{selected_year}年 月別収支")
            monthly_sum = (
                target.groupby(["month_num", "type"])["amount"].sum().unstack(fill_value=0)
            )
            monthly_sum = monthly_sum.reindex(range(1, 13), fill_value=0)

            fig = go.Figure()
            if "income" in monthly_sum.columns:
                fig.add_bar(
                    x=MONTH_LABELS, y=monthly_sum["income"], name="収入", marker_color=DIVERGING_POSITIVE
                )
            if "expense" in monthly_sum.columns:
                fig.add_bar(
                    x=MONTH_LABELS, y=-monthly_sum["expense"], name="支出", marker_color=DIVERGING_NEGATIVE
                )
            fig.update_layout(barmode="relative", legend_title_text="", yaxis_title="金額(円)")
            st.plotly_chart(fig, width="stretch")

            st.subheader(f"{selected_year}年 種目別×月別 収支表")
            st.caption(
                "種目(大項目)は、下の「カテゴリ分類ルール」でご自身で設定した内容です。"
                "まだルールが無い明細は「未分類」になります。"
            )
            target["item"] = target["major_category"]
            pivot = target.pivot_table(
                index="item", columns="month_num", values="signed_amount", aggfunc="sum", fill_value=0
            )
            pivot = pivot.reindex(columns=range(1, 13), fill_value=0)
            pivot.columns = MONTH_LABELS
            pivot.index.name = "種目"
            pivot.columns.name = None
            pivot["年間合計"] = pivot.sum(axis=1)
            pivot = pivot.sort_values("年間合計")

            max_abs = _safe_abs_max(pivot)
            styled = pivot.style.format("¥{:,.0f}").background_gradient(
                cmap=_diverging_cmap(), vmin=-max_abs, vmax=max_abs, axis=None
            )
            st.dataframe(styled, width="stretch")

            with st.expander("複数の年を並べて比較する"):
                compare_years = st.multiselect("比較したい年", years, default=[selected_year])
                for y in compare_years:
                    y_tx = tx[
                        (tx["year"] == y)
                        & (~tx["is_transfer"].astype(bool))
                        & (~tx["is_excluded"].astype(bool))
                    ].copy()
                    if y_tx.empty:
                        continue
                    y_tx["item"] = y_tx["major_category"]
                    y_tx["signed_amount"] = y_tx.apply(
                        lambda r: r["amount"] if r["type"] == "income" else -r["amount"], axis=1
                    )
                    y_pivot = y_tx.pivot_table(
                        index="item", columns="month_num", values="signed_amount",
                        aggfunc="sum", fill_value=0,
                    )
                    y_pivot = y_pivot.reindex(columns=range(1, 13), fill_value=0)
                    y_pivot.columns = MONTH_LABELS
                    y_pivot.index.name = "種目"
                    y_pivot.columns.name = None
                    st.markdown(f"**{y}年**")
                    st.dataframe(y_pivot.style.format("¥{:,.0f}"), width="stretch")

            st.subheader("明細一覧")
            st.caption(
                "「大項目」「中項目」の欄は、この場で直接書き換えられます。変更すると、"
                "その明細と同じ「内容」を持つルールが自動的に作られ(既にあれば更新され)、"
                "同じ内容の他の明細にもすぐ反映されます。新しい項目名を直接入力することも、"
                "「⚙️ カテゴリ設定」タブで登録済みの項目名をそのまま入力することもできます。"
            )
            selected_month_label = st.selectbox("月で絞り込む", ["すべて"] + MONTH_LABELS)
            list_df = year_tx
            if selected_month_label != "すべて":
                month_num = MONTH_LABELS.index(selected_month_label) + 1
                list_df = list_df[list_df["month_num"] == month_num]
            display_df = list_df[
                ["date", "description", "amount", "type", "major_category", "minor_category", "account_name"]
            ].sort_values("date", ascending=False).reset_index(drop=True)
            display_df["type"] = display_df["type"].map(TRANSACTION_TYPE_LABELS).fillna(display_df["type"])
            display_df["minor_category"] = display_df["minor_category"].fillna("")
            display_df["account_name"] = display_df["account_name"].fillna("")

            # 明細一覧の表(の編集内容)は、処理し終わったら消しておかないと、
            # 次に画面を再描画したときに同じ変更をもう一度処理してしまう
            # (ウィジェットを作った後にその値を書き換えることはできないため、
            # 「次の描画で、表を作る前に消す」というやり方にしている)
            editor_key = f"transaction_editor_{selected_year}_{selected_month_label}"
            clear_target = st.session_state.pop("transaction_editor_should_clear", None)
            if clear_target:
                st.session_state.pop(clear_target, None)

            st.data_editor(
                display_df.rename(columns=TRANSACTION_COLUMN_LABELS),
                width="stretch",
                hide_index=True,
                disabled=["日付", "内容", "金額", "収支", "口座"],
                key=editor_key,
            )

            editor_state = st.session_state.get(editor_key)
            if editor_state and editor_state.get("edited_rows"):
                applied = []
                for row_pos, changes in editor_state["edited_rows"].items():
                    if "大項目" not in changes and "中項目" not in changes:
                        continue
                    original_row = display_df.iloc[int(row_pos)]
                    new_major = str(changes.get("大項目", original_row["major_category"]) or "").strip()
                    new_minor = str(changes.get("中項目", original_row["minor_category"]) or "").strip()
                    if not new_major:
                        continue
                    upsert_category_rule(conn, original_row["description"], new_major, new_minor or None)
                    applied.append((original_row["description"], new_major, new_minor))
                if applied:
                    st.session_state["transaction_editor_should_clear"] = editor_key
                    names = "、".join(f"「{desc}」→{major}" for desc, major, _ in applied)
                    st.success(f"カテゴリを更新しました: {names}")
                    st.rerun()

            st.subheader("🏷️ カテゴリ分類ルールを管理する")
            st.caption(
                "明細の「内容」にキーワードが含まれていたら、大項目・中項目を自動で割り当てる"
                "ルールです。複数のルールが一致する場合は、一番最近登録・変更したルールが"
                "優先されます。"
            )

            uncategorized_counts = (
                tx.loc[tx["major_category"] == "未分類", "description"].value_counts().head(30)
            )
            keyword_options = ["(自由入力する)"] + uncategorized_counts.index.tolist()
            picked_description = st.selectbox(
                "未分類の明細から選ぶ(件数が多いものから表示。選ばず自由入力もできます)",
                keyword_options,
                key="rule_picked_description",
            )
            default_keyword = "" if picked_description == "(自由入力する)" else picked_description
            keyword_input = st.text_input(
                "キーワード(明細の「内容」に含まれる文字列)",
                value=default_keyword,
                key="rule_keyword_input",
            )

            new_major_marker = "(新しく入力する)"
            major_options = [new_major_marker] + _major_category_options()
            major_choice = st.selectbox("大項目", major_options, key="rule_major_choice")
            if major_choice == new_major_marker:
                major_value = st.text_input("新しい大項目の名前", key="rule_major_new")
            else:
                major_value = major_choice

            no_minor_marker = "(なし)"
            new_minor_marker = "(新しく入力する)"
            minor_candidates = _minor_category_options(major_choice) if major_choice != new_major_marker else []
            minor_options = [no_minor_marker, new_minor_marker] + minor_candidates
            minor_choice = st.selectbox("中項目", minor_options, key="rule_minor_choice")
            if minor_choice == new_minor_marker:
                minor_value = st.text_input("新しい中項目の名前", key="rule_minor_new")
            elif minor_choice == no_minor_marker:
                minor_value = ""
            else:
                minor_value = minor_choice

            if st.button("このルールを保存する", key="rule_save_button"):
                if not keyword_input.strip() or not major_value.strip():
                    st.warning("キーワードと大項目は、両方とも入力してください。")
                else:
                    upsert_category_rule(conn, keyword_input, major_value.strip(), minor_value.strip() or None)
                    st.success(f"ルールを保存しました:「{keyword_input}」→ {major_value.strip()}")
                    st.rerun()

            st.markdown("**登録済みのルール一覧**")
            if rules_df.empty:
                st.caption("まだルールが登録されていません。")
            else:
                rules_sorted_df = rules_df.sort_values("updated_at", ascending=False)
                rules_display = rules_sorted_df[
                    ["keyword", "major_category", "minor_category", "updated_at"]
                ].rename(
                    columns={
                        "keyword": "キーワード",
                        "major_category": "大項目",
                        "minor_category": "中項目",
                        "updated_at": "更新日時",
                    }
                )
                st.dataframe(rules_display, width="stretch", hide_index=True)

                col_del1, col_del2 = st.columns([3, 1])
                delete_keyword = col_del1.selectbox(
                    "削除するルールのキーワード", rules_sorted_df["keyword"].tolist()
                )
                if col_del2.button("このルールを削除する"):
                    rule_id = int(rules_sorted_df.loc[rules_sorted_df["keyword"] == delete_keyword, "id"].iloc[0])
                    delete_category_rule(conn, rule_id)
                    st.success(f"ルール「{delete_keyword}」を削除しました。")
                    st.rerun()

# ---------------------------------------------------------------------------
# 楽天証券(NISA)
# ---------------------------------------------------------------------------
with tab_nisa:
    holdings = pd.read_sql_query(
        "SELECT * FROM holdings_snapshots WHERE type != '預金・現金' ORDER BY snapshot_date", conn
    )

    if holdings.empty:
        st.info(
            "NISA資産データがまだありません。ターミナルで `python src/scrape_portfolio.py` を"
            "実行してください(毎月20日ごろに実行するのがおすすめです)。"
        )
    else:
        latest_date = holdings["snapshot_date"].max()
        latest = holdings[holdings["snapshot_date"] == latest_date]

        col1, col2 = st.columns(2)
        col1.metric(f"NISA評価額合計({latest_date}時点)", f"¥{latest['balance'].sum():,.0f}")
        col2.metric("評価損益合計", f"¥{latest['unrealized_gain'].sum():,.0f}")

        st.subheader("資産推移(評価額合計)")
        trend = holdings.groupby("snapshot_date")["balance"].sum().reset_index()
        fig = px.line(trend, x="snapshot_date", y="balance", markers=True)
        fig.update_traces(line_color=CATEGORICAL_COLORS[0])
        fig.update_layout(yaxis_title="評価額(円)", xaxis_title="")
        st.plotly_chart(fig, width="stretch")

        st.subheader("銘柄別の推移")
        names = sorted(holdings["name"].unique())
        default_names = latest.sort_values("balance", ascending=False)["name"].tolist()[:8]
        selected_names = st.multiselect("表示する銘柄(見やすさのため8件までを推奨)", names, default=default_names)
        selected_metric = st.selectbox(
            "比較する項目", list(METRIC_LABELS.keys()), format_func=lambda k: METRIC_LABELS[k]
        )

        if selected_names:
            filtered = holdings[holdings["name"].isin(selected_names)]

            fig2 = go.Figure()
            for i, name in enumerate(selected_names):
                series = filtered[filtered["name"] == name].sort_values("snapshot_date")
                fig2.add_scatter(
                    x=series["snapshot_date"],
                    y=series[selected_metric],
                    mode="lines+markers",
                    name=name,
                    line_color=categorical_color(i),
                )
            fig2.update_layout(title=f"{METRIC_LABELS[selected_metric]}の推移", legend_title_text="")
            st.plotly_chart(fig2, width="stretch")

            st.subheader("銘柄×取得日 の比較表")
            metric_pivot = filtered.pivot_table(
                index="name", columns="snapshot_date", values=selected_metric, aggfunc="last"
            )
            metric_pivot.index.name = "銘柄名"
            metric_pivot.columns.name = "取得日"
            if selected_metric in DIVERGING_METRICS:
                max_abs = _safe_abs_max(metric_pivot)
                styled_metric = metric_pivot.style.format("{:,.1f}", na_rep="-").background_gradient(
                    cmap=_diverging_cmap(), vmin=-max_abs, vmax=max_abs, axis=None
                )
            else:
                styled_metric = metric_pivot.style.format("{:,.1f}", na_rep="-").background_gradient(
                    cmap=_sequential_cmap(), axis=None
                )
            st.dataframe(styled_metric, width="stretch")

        st.subheader(f"銘柄別の内訳({latest_date}時点)")
        holdings_display = latest[
            [
                "type",
                "name",
                "code",
                "institution",
                "quantity",
                "unit_price",
                "balance",
                "unrealized_gain",
                "unrealized_gain_pct",
            ]
        ].sort_values("balance", ascending=False)
        holdings_display["code"] = holdings_display["code"].fillna("")
        holdings_display["institution"] = holdings_display["institution"].fillna("")
        st.dataframe(
            holdings_display.rename(columns=HOLDINGS_COLUMN_LABELS),
            width="stretch",
            hide_index=True,
        )

# ---------------------------------------------------------------------------
# セゾンカード
# ---------------------------------------------------------------------------
with tab_saison:
    card_tx = pd.read_sql_query("SELECT * FROM card_transactions", conn)

    if card_tx.empty:
        st.info(
            "セゾンカードのデータがまだありません。セゾンカードの会員サイトからダウンロードした"
            "CSVファイルを `data/saison_csv` フォルダに置いてから、ターミナルで "
            "`python src/import_saison_csv.py` を実行してください。"
        )
    else:
        card_tx["year_month"] = card_tx["date"].str[:7]

        card_names = sorted(card_tx["card_name"].unique())
        selected_card = st.selectbox("カードを選ぶ", ["すべて"] + card_names)
        card_filtered = (
            card_tx if selected_card == "すべて" else card_tx[card_tx["card_name"] == selected_card]
        )

        st.subheader("月別 利用金額の推移")
        monthly = (
            card_filtered.groupby("year_month")["amount"].sum().reset_index().sort_values("year_month")
        )
        fig = go.Figure()
        fig.add_bar(x=monthly["year_month"], y=monthly["amount"], marker_color=CATEGORICAL_COLORS[1])
        fig.update_layout(yaxis_title="利用金額(円)", xaxis_title="")
        st.plotly_chart(fig, width="stretch")

        months = sorted(card_filtered["year_month"].unique(), reverse=True)
        selected_month = st.selectbox("年月で絞り込む", ["すべて"] + months)
        list_df = (
            card_filtered
            if selected_month == "すべて"
            else card_filtered[card_filtered["year_month"] == selected_month]
        )

        st.metric("この期間の利用金額合計", f"¥{list_df['amount'].sum():,.0f}")

        st.subheader("利用明細")
        card_display = list_df[
            ["date", "card_name", "description", "amount", "payment_type", "family_member", "note"]
        ].sort_values("date", ascending=False)
        st.dataframe(
            card_display.rename(columns=CARD_COLUMN_LABELS),
            width="stretch",
            hide_index=True,
        )

# ---------------------------------------------------------------------------
# カテゴリ設定
# ---------------------------------------------------------------------------
with tab_settings:
    st.subheader("大項目・中項目の一覧")
    st.caption(
        "ここであらかじめ登録しておくと、楽天銀行タブでカテゴリを設定するときに、"
        "一覧から選べるようになります。ルールや明細一覧で新しい項目名を使った場合も、"
        "自動的にここへ追加されます。"
    )

    # 入力欄をクリアしたい場合、ウィジェットを作った後にその値を書き換えることは
    # Streamlitの仕様上できないため、次の実行の「ウィジェットを作る前」に
    # クリアする、というやり方にしている
    if st.session_state.pop("settings_form_should_clear", False):
        st.session_state["settings_new_major"] = ""
        st.session_state["settings_new_minor"] = ""

    new_major = st.text_input("大項目", key="settings_new_major")
    new_minor = st.text_input("中項目(任意)", key="settings_new_minor")
    if st.button("登録する", key="settings_add_button"):
        if not new_major.strip():
            st.warning("大項目を入力してください。")
        else:
            upsert_category(conn, new_major, new_minor)
            st.success(f"「{new_major.strip()}」を登録しました。")
            st.session_state["settings_form_should_clear"] = True
            st.rerun()

    st.markdown("**登録済みの一覧**")
    if categories_df.empty:
        st.caption("まだ登録された項目がありません。")
    else:
        categories_display = categories_df[["major_category", "minor_category"]].rename(
            columns={"major_category": "大項目", "minor_category": "中項目"}
        )
        st.dataframe(categories_display, width="stretch", hide_index=True)

        delete_labels = [
            f"{row.major_category} / {row.minor_category}" if row.minor_category else row.major_category
            for row in categories_df.itertuples()
        ]
        col_del1, col_del2 = st.columns([3, 1])
        delete_choice = col_del1.selectbox("削除する項目", delete_labels, key="settings_delete_choice")
        if col_del2.button("削除する", key="settings_delete_button"):
            category_id = int(categories_df.iloc[delete_labels.index(delete_choice)]["id"])
            delete_category(conn, category_id)
            st.success(f"「{delete_choice}」を削除しました。")
            st.rerun()
