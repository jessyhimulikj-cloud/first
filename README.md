# A股股票 AI 投资分析系统

这是一个使用 Python 开发的 A 股股票 AI 投资分析 CLI。第一版支持用户输入股票代码（例如 `002594`），自动从 Tushare Pro 获取基础信息、最近一年日 K 线、财务与估值数据，计算常用技术指标，并调用 DeepSeek API 生成多周期分析报告。

> 免责声明：本项目输出内容仅供参考，不构成投资建议。市场有风险，投资需谨慎。

## 功能

- 获取股票基础信息：代码、名称、地区、行业、市场、上市日期。
- 获取最近一年日 K 线数据。
- 计算技术指标：
  - MA5、MA10、MA20、MA60
  - RSI14
  - MACD
  - 成交量变化
  - 近 20 日涨跌幅
- 获取财务数据：
  - 营收
  - 归母净利润
  - ROE
  - 毛利率
  - 资产负债率
- 获取估值数据：
  - PE
  - PB
  - 总市值
- 调用 DeepSeek API 生成：
  - 短期投资建议（3-5 个交易日）
  - 中期投资建议（2-3 个月）
  - 长期投资建议（1 年左右）
  - 风险提示
  - 综合评分
  - 是否适合当前买入

## 环境要求

- Windows 11
- Python 3.10+
- VS Code 或任意终端
- Tushare Pro Token
- DeepSeek API Key

## 安装

在 VS Code 终端中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置 API Key

API Key 必须从环境变量读取，不能写死在代码里。

PowerShell 示例：

```powershell
setx TUSHARE_TOKEN "你的TushareToken"
setx DEEPSEEK_API_KEY "你的DeepSeekKey"
```

设置完成后，请重新打开 VS Code 终端，让环境变量生效。

如需切换 DeepSeek 模型，可选设置：

```powershell
setx DEEPSEEK_MODEL "deepseek-chat"
```

## 使用方法

命令行传入股票代码：

```powershell
python a_stock_ai_analyzer.py 002594
```

或直接运行后按提示输入：

```powershell
python a_stock_ai_analyzer.py
```

程序会逐步打印当前执行进度；如果 Tushare 或 DeepSeek 数据获取失败，会显示友好的错误提示。

## 注意事项

- Tushare Pro 部分接口需要相应积分或权限。
- 财务报表披露有滞后性，报告中的财务数据以 Tushare 当前可获取数据为准。
- AI 生成内容可能存在遗漏或偏差，请结合公开公告、研报、交易所信息和个人风险承受能力综合判断。
- 本系统不会直接给出绝对买卖指令，所有输出均为“仅供参考，不构成投资建议”。
