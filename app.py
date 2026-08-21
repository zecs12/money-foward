"""
取得した家計データ(明細・資産)を、自分のパソコンの中だけで見るための
ダッシュボード。

使い方:
    streamlit run app.py

コマンドを実行すると、自動的にブラウザが開いて画面が表示されます
(http://localhost:8501)。インターネットには公開されず、自分のパソコンの
中だけで完結します。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from db import DB_PATH, get_connection  # noqa: E402

st.set_page_config(page_title="家計データダッシュボード", layout="wide")
st.title("家計データダッシュボード")

if not DB_PATH.exists():
    st.warning(
        "まだデータがありません。先にターミナルで `python src/run_scrape.py --full` を"
        "実行して、データを取得してください。"
    )
    st.stop()

conn = get_connection()

tab_cash_flow, tab_portfolio = st.tabs(["家計簿(明細)", "NISA・資産"])

with tab_cash_flow:
    df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date DESC", conn)

    if df.empty:
        st.info(
            "明細データがまだありません。ターミナルで "
            "`python src/scrape_cash_flow.py --full` を実行してください。"
        )
    else:
        months = sorted(df["month"].unique(), reverse=True)
        selected_month = st.selectbox("表示する月", ["すべて"] + months)

        filtered = df if selected_month == "すべて" else df[df["month"] == selected_month]
        # 振替(口座間の資金移動)・計算対象外の行は、収支の集計からは除く
        target = filtered[
            (~filtered["is_transfer"].astype(bool)) & (~filtered["is_excluded"].astype(bool))
        ]

        income = target[target["type"] == "income"]["amount"].sum()
        expense = target[target["type"] == "expense"]["amount"].sum()

        col1, col2, col3 = st.columns(3)
        col1.metric("収入", f"¥{income:,.0f}")
        col2.metric("支出", f"¥{expense:,.0f}")
        col3.metric("収支", f"¥{income - expense:,.0f}")

        st.subheader("月別 収支の推移")
        monthly = (
            df[(~df["is_transfer"].astype(bool)) & (~df["is_excluded"].astype(bool))]
            .groupby(["month", "type"])["amount"]
            .sum()
            .unstack(fill_value=0)
        )
        st.bar_chart(monthly)

        st.subheader("明細一覧")
        st.dataframe(
            filtered[
                [
                    "date",
                    "description",
                    "amount",
                    "type",
                    "category",
                    "sub_category",
                    "account_name",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

with tab_portfolio:
    df = pd.read_sql_query("SELECT * FROM holdings_snapshots ORDER BY snapshot_date DESC", conn)

    if df.empty:
        st.info(
            "資産データがまだありません。ターミナルで "
            "`python src/scrape_portfolio.py` を実行してください。"
        )
    else:
        latest_date = df["snapshot_date"].max()
        st.caption(f"最新の取得日: {latest_date}")

        latest = df[df["snapshot_date"] == latest_date]

        total_balance = latest["balance"].sum()
        st.metric("資産合計(最新)", f"¥{total_balance:,.0f}")

        st.subheader("資産推移")
        trend = df.groupby("snapshot_date")["balance"].sum()
        st.line_chart(trend)

        st.subheader("銘柄別の内訳(最新)")
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
            use_container_width=True,
            hide_index=True,
        )
