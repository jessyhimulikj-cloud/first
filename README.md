# 自动选股系统（资金流 + 热点）

这是一个可落地的 **自动选股打分脚本**，支持三种数据源：

- `csv`：本地 CSV 数据
- `eastmoney`：东方财富实时接口（行情 + 资金流）
- `akshare`：akshare 行情 + 资金流 + 热点板块（简化）

核心融合因子：
- 资金流（主力净流入、超大单净流入、主力流入占比）
- 动量（涨跌幅、量比）
- 流动性（换手率、量比）
- 热点题材热度（题材热度 + 个股题材映射）

> 说明：本项目是策略研究与工程模板，不构成投资建议。

---

## 1. 环境要求

- Python `3.12`（Windows / Linux / macOS）
- 推荐先创建虚拟环境

### Windows（PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pytest akshare pandas
```

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
pip install pytest akshare pandas
```

---

## 2. 快速开始

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
  --top 3 \
  --output picked_stocks.csv
```

### 方式 C：akshare（推荐）

```bash
python stock_picker.py \
  --source akshare \
  --ak-limit 200 \
  --ak-board-top 8 \
  --ak-board-cons-limit 40 \
  --top 3 \
  --output picked_stocks.csv
```

> `akshare` 模式下如果不传 `--theme` / `--theme-map`，程序会自动构造“简化热点板块映射”。

---

## 3. 每天自动筛选 Top3

```bash
python stock_picker.py \
  --source akshare \
  --top 3 \
  --auto-daily \
  --daily-time 15:10 \
  --output picked_stocks.csv
```

说明：
- 每天到 `15:10` 自动执行一次
- 结果会覆盖写入 `picked_stocks.csv`

---

## 4. 输入数据格式（CSV 模式）

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
- `main_net_inflow` 主力净流入
- `super_net_inflow` 超大单净流入
- `main_inflow_ratio` 主力流入占比（%）

### `theme.csv`
必需字段：
- `theme` 题材名称
- `heat_score` 题材热度分

### `theme_map.csv`
必需字段：
- `ts_code`
- `theme`

---

## 5. 命令行参数

- `--source`：`csv` / `eastmoney` / `akshare`
- `--market`、`--flow`：CSV 模式必填
- `--theme`、`--theme-map`：可选
- `--em-page-size`：东方财富拉取股票数
- `--ak-limit`：akshare 拉取股票数
- `--ak-board-top`：akshare 热点板块数量
- `--ak-board-cons-limit`：每个热点板块的成分股上限
- `--top`：输出前 N 只股票（默认 3）
- `--output`：输出文件，默认 `picked_stocks.csv`
- `--auto-daily`：开启每日自动运行
- `--daily-time`：每日运行时间 `HH:MM`
- 四个权重参数：`--w-money-flow`、`--w-momentum`、`--w-liquidity`、`--w-hot-theme`

---

## 6. 测试

```bash
pytest -q
```
