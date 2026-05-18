# first

A 股股票 AI 投资分析与离线评估工具。

## 在线分析

`a_stock_ai_analyzer.py` 通过 Tushare Pro 获取行情、估值和财务数据，并调用 DeepSeek 生成结构化中文分析报告。运行前需要设置：

- `TUSHARE_TOKEN`
- `DEEPSEEK_API_KEY`
- 可选：`DEEPSEEK_MODEL`

```bash
python a_stock_ai_analyzer.py 002594
```

## 离线报告回放评估

`offline_report_eval.py` 会读取 `data/*.csv` 中的历史行情，选择一个过去日期作为分析时点，只使用该日期及之前的行情计算技术指标，生成当时可得到的短期/中期/长期技术判断，并对比之后 5、20、60 个交易日的收益、最大回撤、命中情况和风险暴露。

脚本不依赖外部 API，也不需要联网；它只使用 Python 标准库，适合在没有密钥的环境中快速回测报告框架。

```bash
python offline_report_eval.py --as-of-date 2025-10-01 --limit 10
```

常用参数：

- `--data-dir data`：CSV 行情目录，默认读取 `data/*.csv`。
- `--as-of-date 2025-10-01`：分析时点，支持 `YYYY-MM-DD` 或 `YYYYMMDD`。
- `--horizons 5,20,60`：后验评估周期，默认 5、20、60 个交易日。
- `--output offline_eval.json`：输出完整报告和评估明细 JSON。
- `--limit 10`：抽样评估前 N 只股票。

离线报告质量检查项包括：

- 是否引用了具体数据。
- 是否给出触发条件。
- 是否给出失效条件。
- 是否区分短中长期。
- 是否说明反方观点。
