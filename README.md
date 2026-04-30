# A股短线模型（3-5天）

该项目已升级为更贴近中国A股短线交易的基线模型：
- 股票池：默认取沪深A股前200只；
- 数据：最近1年日线下载到本地 `data_a_share/`；
- 过滤规则：涨跌停过滤、停牌过滤、一字板过滤；
- 因子：3/5日动量 + 波动率惩罚 + 量比 + 换手率因子；
- 交易管理：分层仓位、止损止盈、最短/最长持有期（3-5天）。

> 注意：仅用于量化研究与回测验证，不构成投资建议。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行

```bash
python stock_short_term_model.py --top-n 200 --pick-count 6 --hold-min 3 --hold-max 5 --stop-loss -0.05 --take-profit 0.08 --download
```

如果已在 `data_a_share/` 放好 CSV（文件名如 `600000.SH.csv`），可以不加 `--download` 做离线回测。

## 数据格式（本地CSV）
至少应包含列：
- `Date`, `Open`, `High`, `Low`, `Close`, `Volume`
- 可选：`TurnoverRate`

## 输出
- `output/daily_picks.csv`：每日入选股票、分层权重、退出原因、收益
- `output/backtest_pnl.csv`：组合日收益和净值曲线
