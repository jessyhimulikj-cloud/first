# Tushare + DeepSeek 短线 AI 选股系统

本项目是一个用于量化研究和交易辅助学习的短线 A 股选股系统，主流程围绕：

- **Tushare 数据**：股票基础信息、历史日线、每日指标、资金流、沪深300指数。
- **主线热点**：识别行业/主题热度，优先选择市场主线前排。
- **情绪周期**：判断市场处于冰点、修复、主升、高潮或退潮阶段。
- **龙头股识别**：在主线内寻找成交额、涨幅、趋势和相对强度靠前的核心标的。
- **趋势强化**：确认 `close > ma5 > ma10` / `close > ma5 > ma10 > ma20`、动量和放量质量。
- **DeepSeek 二次分析**：从量化候选池中精选 3 只短线观察标的，并输出原因、操作计划和风险点。

> 免责声明：本项目仅用于量化研究、程序开发和交易辅助学习，不构成任何投资建议。股票交易存在亏损风险，使用者应自行判断并承担全部风险。模型输出不代表未来收益，也不保证准确性。

---

## 1. 环境变量

```bash
export TUSHARE_TOKEN="你的 Tushare Token"
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-chat"
```

说明：

- `TUSHARE_TOKEN` 用于下载和更新行情数据。
- `DEEPSEEK_API_KEY` 只有在使用 `--enable-ai-analysis` 时需要。
- 未启用 DeepSeek 或未配置 API Key 时，系统仍会输出量化 Top3，AI 字段使用回退说明。

---

## 2. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install pandas tushare requests pytest
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pandas tushare requests pytest
```

---

## 3. 更新数据

```bash
python update_data.py \
  --months 12 \
  --universe-size 300 \
  --data-dir data
```

更新脚本会尽量更新：

- 股票基础信息缓存
- 股票历史日线 CSV
- 沪深300指数缓存

如只想使用已有缓存调试，可跳过基础信息或指数：

```bash
python update_data.py --skip-basic --skip-index
```

---

## 4. 单次量化选股

```bash
python stock_picker.py \
  --source tushare \
  --top 3 \
  --output picked_stocks.csv
```

默认输出：

- `picked_stocks.csv`：最终 3 只短线观察标的
- `candidate_pool.csv`：量化候选池，默认前 20 只
- `market_sentiment.json`：市场情绪周期
- `hot_themes.csv`：主线热点排名

---

## 5. 启用 DeepSeek 分析

```bash
python stock_picker.py \
  --source tushare \
  --top 3 \
  --enable-ai-analysis \
  --ai-candidate-size 20 \
  --output picked_stocks.csv
```

DeepSeek 的职责不是从全市场直接选股，而是基于量化候选池做二次判断，最终输出 3 只标的，并给出：

- 入选原因
- 龙头判断
- 趋势判断
- 买入观察条件
- 仓位建议
- 止损和止盈规则
- 最长持有天数
- 风险点

---

## 6. 短线策略逻辑

总分模型：

```python
total_score = (
    hot_theme_score * 0.30
    + sentiment_cycle_score * 0.15
    + leader_score * 0.25
    + trend_strength_score * 0.20
    + liquidity_score * 0.10
)
```

### 主线热点

热点分数由行业/主题 1 日、3 日、5 日表现、成交额占比、强势股数量等构成。系统优先选择主线排名前 20% 的股票。

### 情绪周期

系统把市场分为：

- `ice_point`：冰点
- `recovery`：修复
- `main_rise`：主升
- `climax`：高潮
- `decline`：退潮

情绪越弱，操作建议越保守。

### 龙头识别

龙头分数综合：

- 所属主线热度
- 主线内涨幅排名
- 成交额排名
- 放量强度
- 趋势强度
- 近 3 日相对板块强度

### 趋势强化

优先满足：

```text
close > ma5 > ma10 > ma20
```

至少满足：

```text
close > ma5 > ma10
```

并结合 3 日/5 日动量、量比、收盘位置过滤趋势衰竭标的。

---

## 7. 每日运行

立即执行一次：

```bash
python daily_runner.py \
  --once \
  --top 3 \
  --enable-ai-analysis
```

常驻每日运行：

```bash
python daily_runner.py \
  --time 15:10 \
  --top 3 \
  --enable-ai-analysis \
  --output-dir . \
  --history history.csv
```

---

## 8. 回测

```bash
python backtest.py \
  --source tushare \
  --months 6 \
  --universe-size 100 \
  --output backtest_result.csv
```

回测保留原有指标：

- 总交易次数
- 胜率
- 平均收益
- 最大回撤
- 盈亏比
- 年度收益

---

## 9. 主要文件

```text
tushare_data_loader.py       # Tushare 数据获取和缓存
strategy_config.py           # 策略参数配置
theme_analyzer.py            # 主线热点分析
sentiment_analyzer.py        # 市场情绪周期分析
leader_analyzer.py           # 龙头股识别
trend_analyzer.py            # 趋势强化分析
deepseek_client.py           # DeepSeek API 客户端
stock_picker.py              # 主选股入口
daily_runner.py              # 每日运行入口
backtest.py                  # 回测
update_data.py               # 批量更新数据
```

---

## 10. 测试

```bash
pytest -q
```

测试会 mock 外部接口，不应真实请求 Tushare 或 DeepSeek。
