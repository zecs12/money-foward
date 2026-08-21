"""
ダッシュボードのグラフ・表で使う色の定義。

色の使い分けの考え方:
- カテゴリ(銘柄名・項目名など、種類を区別したいだけのもの)には「分類用の色」を、
  決まった順番で割り当てる(毎回同じ色が同じ意味にならないよう、順番を変えない)。
- 金額のプラス/マイナス(収入か支出か、含み益か含み損か)のように、
  「0を境にした正反対の意味」を表す場合は「発散配色(青↔赤)」を使う。
- 良い/悪いの状態を表す場合は「ステータス色」を使う。
"""

# 分類用の色(種類を区別するための色。決まった順番で使う)
CATEGORICAL_COLORS = [
    "#2a78d6",  # 1: blue
    "#eb6834",  # 2: orange
    "#1baf7a",  # 3: aqua
    "#eda100",  # 4: yellow
    "#e87ba4",  # 5: magenta
    "#008300",  # 6: green
    "#4a3aa7",  # 7: violet
    "#e34948",  # 8: red
]

# 発散配色(0を境にした正反対の意味。青=プラス、赤=マイナス)
DIVERGING_POSITIVE = "#2a78d6"  # 収入・含み益 など
DIVERGING_NEGATIVE = "#e34948"  # 支出・含み損 など
DIVERGING_NEUTRAL = "#f0efec"  # 0付近

# ステータス色(良い/悪いの状態)
STATUS_GOOD = "#0ca30c"
STATUS_CRITICAL = "#d03b3b"

# 文字色
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
TEXT_MUTED = "#898781"
GRIDLINE = "#e1e0d9"


def categorical_color(index: int) -> str:
    """index番目の分類用の色を返す(色が足りない場合は最後の色を繰り返す)。"""
    if index < len(CATEGORICAL_COLORS):
        return CATEGORICAL_COLORS[index]
    return CATEGORICAL_COLORS[-1]
