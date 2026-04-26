# 自动选股系统（资金流 + 热点）

这是一个可落地的 **自动选股打分脚本**，支持两种数据源：

- `csv`：本地 CSV 数据
- `eastmoney`：东方财富实时接口（行情 + 资金流）

核心融合因子：
- 资金流（主力净流入、超大单净流入、主力流入占比）
- 动量（涨跌幅、量比）
- 流动性（换手率、量比）
- 热点题材热度（题材热度 + 个股题材映射，可选）

> 说明：本项目是策略研究与工程模板，不构成投资建议。

---

## 1. 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install pytest
```

### 方式 A：CSV

```bash
python stock_picker.py \
  --source csv \
  --market sample_data/market.csv \
  --flow sample_data/flow.csv \
  --theme sample_data/theme.csv \
  --theme-map sample_data/theme_map.csv \
  --top 3 \
  --output picked_stocks.csv
```

### 方式 B：东方财富

```bash
python stock_picker.py \
  --source eastmoney \
  --em-page-size 200 \
  --top 20 \
  --output picked_stocks.csv
```

> 如果你有本地题材数据，也可以和东方财富行情混用：追加 `--theme` 和 `--theme-map`。

---

## 2. 输入数据格式（CSV 模式）

### `market.csv`
必需字段：
- `ts_code` 股票代码（如 `000001.SZ`）
- `name` 股票名称
- `close` 收盘价
- `pct_chg` 当日涨跌幅（%）
- `vol_ratio` 量比
- `turnover_rate` 换手率（%）

### `flow.csv`
必需字段：
- `ts_code`
- `main_net_inflow` 主力净流入（可统一到万元）
- `super_net_inflow` 超大单净流入
- `main_inflow_ratio` 主力流入占比（%）

### `theme.csv`（可选）
必需字段：
- `theme` 题材名称
- `heat_score` 题材热度分

### `theme_map.csv`（可选）
必需字段：
- `ts_code`
- `theme`

---

## 3. 打分逻辑

### 3.1 因子计算
- `money_flow_raw = 0.55*main_net_inflow + 0.25*super_net_inflow + 0.20*main_inflow_ratio`
- `momentum_raw = 0.7*pct_chg + 0.3*vol_ratio`
- `liquidity_raw = 0.6*turnover_rate + 0.4*vol_ratio`

### 3.2 标准化
使用鲁棒 z-score（基于 median + MAD），降低极端值影响。

### 3.3 热点分
`theme_map` 关联 `theme` 后，对个股关联题材热度 z-score 做均值，得到 `hot_theme_score`。

### 3.4 总分
默认权重：
- 资金流 `0.45`
- 动量 `0.25`
- 流动性 `0.15`
- 热点 `0.15`

权重可通过参数调整，且要求权重和为 1。

---

## 4. 命令行参数

- `--source` 数据源：`csv` / `eastmoney`（默认 `csv`）
- `--market` 行情 CSV（`source=csv` 时必填）
- `--flow` 资金流 CSV（`source=csv` 时必填）
- `--theme` 题材热度 CSV（可选）
- `--theme-map` 个股题材映射 CSV（可选）
- `--em-page-size` 东方财富拉取股票数量（默认 `200`）
- `--top` 输出前 N 只股票，默认 `20`
- `--output` 输出文件路径，默认 `picked_stocks.csv`
- `--w-money-flow` 资金流权重（默认 `0.45`）
- `--w-momentum` 动量权重（默认 `0.25`）
- `--w-liquidity` 流动性权重（默认 `0.15`）
- `--w-hot-theme` 热点权重（默认 `0.15`）

---

## 5. 测试

```bash
pytest -q
```

---

## 6. 可继续扩展

- 增加交易日历和盘中/盘后定时任务
- 新增风控（ST 过滤、停牌过滤、财务风险过滤）
- 做回测（分层收益、换手、最大回撤）
- 加入行业中性化、规模中性化处理
