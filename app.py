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

from db import DB_PATH, get_connection  # noqa: E402
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

tab_bank, tab_nisa, tab_saison = st.tabs(
    ["🏦 楽天銀行(家計簿)", "📈 楽天証券(NISA)", "💳 セゾンカード"]
)

# ---------------------------------------------------------------------------
# 楽天銀行(家計簿)
# ---------------------------------------------------------------------------
with tab_bank:
    tx = pd.read_sql_query("SELECT * FROM transactions", conn)

    if tx.empty:
        st.info(
            "明細データがまだありません。ターミナルで "
            "`python src/scrape_cash_flow.py --full` を実行してください。"
        )
    else:
        tx["year"] = tx["date"].str[:4]
        tx["month_num"] = tx["date"].str[5:7].astype(int)

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
            target["category"] = target["category"].fillna("(未分類)")
            pivot = target.pivot_table(
                index="category", columns="month_num", values="signed_amount", aggfunc="sum", fill_value=0
            )
            pivot = pivot.reindex(columns=range(1, 13), fill_value=0)
            pivot.columns = MONTH_LABELS
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
                    y_tx["category"] = y_tx["category"].fillna("(未分類)")
                    y_tx["signed_amount"] = y_tx.apply(
                        lambda r: r["amount"] if r["type"] == "income" else -r["amount"], axis=1
                    )
                    y_pivot = y_tx.pivot_table(
                        index="category", columns="month_num", values="signed_amount",
                        aggfunc="sum", fill_value=0,
                    )
                    y_pivot = y_pivot.reindex(columns=range(1, 13), fill_value=0)
                    y_pivot.columns = MONTH_LABELS
                    st.markdown(f"**{y}年**")
                    st.dataframe(y_pivot.style.format("¥{:,.0f}"), width="stretch")

            st.subheader("明細一覧")
            selected_month_label = st.selectbox("月で絞り込む", ["すべて"] + MONTH_LABELS)
            list_df = year_tx
            if selected_month_label != "すべて":
                month_num = MONTH_LABELS.index(selected_month_label) + 1
                list_df = list_df[list_df["month_num"] == month_num]
            st.dataframe(
                list_df[
                    ["date", "description", "amount", "type", "category", "sub_category", "account_name"]
                ].sort_values("date", ascending=False),
                width="stretch",
                hide_index=True,
            )

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
        st.dataframe(
            latest[
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
            ].sort_values("balance", ascending=False),
            width="stretch",
            hide_index=True,
        )

# ---------------------------------------------------------------------------
# セゾンカード(準備中)
# ---------------------------------------------------------------------------
with tab_saison:
    st.info(
        "セゾンカードのデータ取り込みは、まだ準備中です。CSVファイルの形式を確認できたら、"
        "ここに利用明細の一覧(年月で検索可能)が表示されるようになります。"
    )
