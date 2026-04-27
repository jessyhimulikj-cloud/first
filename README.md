# 自动选股系统（CSV + AkShare）

本项目提供一个可运行的自动选股脚本：

- 保留 `csv` 模式（兼容旧数据流程）
- 新增 `akshare` 模式（真实 A 股行情 + 短线 3-5 天评分）
- 输出 `picked_stocks.csv`
- 支持每天自动筛选 Top3

---

## 1. 环境（Windows + Python 3.12）

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install akshare pandas pytest
```

### Linux/macOS

```bash
python -m venv .venv
source .venv/bin/activate
pip install akshare pandas pytest
```

---

## 2. 运行命令

## 2.1 CSV 模式（保留）

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

## 2.2 AkShare 模式（新）

```bash
python stock_picker.py \
  --source akshare \
  --ak-hist-limit 150 \
  --top 3 \
  --output picked_stocks.csv
```

## 2.3 每天自动筛选 Top3

```bash
python stock_picker.py \
  --source akshare \
  --top 3 \
  --auto-daily \
  --daily-time 15:10 \
  --output picked_stocks.csv
```

---

## 3. AkShare 模式策略逻辑（简化可运行版）

### 数据来源
- A 股实时行情列表：`stock_zh_a_spot_em`
- 个股历史日线（用于 3/5 日涨幅）：`stock_zh_a_hist`

### 风险过滤
- 剔除 ST / 退市
- 剔除北交所（代码 8/4 开头）
- 剔除价格 < 3 元
- 剔除成交额 < 1 亿
- 剔除跌幅 < -5%
- 剔除涨幅 > 9.5%

### 指标与评分
- `momentum_5`：5 日涨幅
- `momentum_3`：3 日涨幅
- `liquidity_z`：成交额的 z 分数
- `pct_chg`：今日涨跌幅

新增短线增强规则：
- 趋势确认（必须满足）：`5日线 > 10日线` 且 `收盘价 > 5日线`
- 放量确认：`今日成交量 > 5日均量 * 1.5`
- 剔除弱势：最近 5 天涨幅 < 0 剔除；最近 3 天有跌停（近似 <= -9.5%）剔除
- 热点强化：仅保留当前涨幅排名前 20% 板块成分股

`total_score = momentum_5 * 0.30 + momentum_3 * 0.20 + liquidity_z * 0.30 + pct_chg * 0.20`

### 输出字段
- `ts_code, name, close, pct_chg, amount, momentum_3, momentum_5, volume_ratio, trend_flag, total_score, risk_flag`

---

## 4. 测试

```bash
pytest -q
```

---

## 5. 回测（新增 backtest.py）

`backtest.py` 用于验证短线策略，默认回测最近 3 个月，并输出 `backtest_result.csv`。

### 运行命令

```bash
python backtest.py --months 3 --universe-size 50 --max-days 60 --output backtest_result.csv
```

### 回测规则（实现）

- 每个交易日收盘：按 `stock_picker` 短线逻辑打分，选 Top3 中分数最高 1 只
- 次日开盘买入
- 三种卖出策略：
  - `hold_3`：持有 3 天
  - `hold_5`：持有 5 天
  - `take_profit_stop_loss`：止盈 +6%，止损 -3%（最多观察 5 天）
  - 默认仅启用 `hold_3`（可用 `--modes` 扩展）

### 输出指标

- 总交易次数
- 胜率
- 平均收益
- 最大回撤
- 盈亏比
- 每年收益

### 性能与稳定性

- 带进度打印（加载数据、回测进度）
- 带异常处理（单标的失败自动跳过）
- 带数据缓存（默认 `.cache_backtest/`，避免重复请求）

---

## 6. 每日自动选股（新增 daily_runner.py）

功能：
- 每天 `15:10` 自动执行
- 调用 `stock_picker.py --source eastmoney`
- 输出 `picked_stocks_日期.csv`
- 累计写入 `history.csv`
- 当天已执行过则自动跳过

### 启动命令（常驻）

```bash
python daily_runner.py --time 15:10 --top 3 --output-dir . --history history.csv
```

### 立即执行一次（调试）

```bash
python daily_runner.py --once --top 3 --output-dir . --history history.csv
```

执行后会打印：
- 今日推荐股票
- 分数
- 买入建议（开盘价附近分批买入）
