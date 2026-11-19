# annual-returns · 年度收益总览

数据与展示分离的年度收益追踪：

- **数据层**：`data/` 下的 JSON，git 留痕；按用途分 4 个子目录（持仓 / 每日归档 / 成本基准 / 借款）
- **展示层**：三个静态页（GitHub Pages 托管），打开时读 JSON 现算现渲染
- **任务层**：`job/daily_update.py`，由 GitHub Actions 执行：拉收盘价 → 追加记录 → commit + push。触发方式：**打开首页时静默自检**——工作日 15:05 后若当日数据未写入，页面后台自动 dispatch（workflow_dispatch）触发一次，10 分钟内不重复；无需手动操作

## 页面

| 页面 | 内容 |
|---|---|
| `index.html` | 年度收益总览：KPI、毛收益 vs 净收益、累计走势、数据明细 |
| `my-account.html` | 股票账户：市值、融资负债、维持担保比例、再平衡监控、本人净资产 |
| `girlfriend-settlement.html` | 女友投资结算：分段计息明细与凭据 |

## 数据文件

```
data/
├── portfolio/positions.json   持仓：代码 / 名称 / 股数 / 成本 / 目标权重 / 溢价快照
├── daily/<年>.json            每日记录：收盘价、份额快照、当日盈亏、溢价/IOPV、updated_at
├── costs/baseline.json        历史存量：各账户历年盈亏、同花顺校准点、融资本金与日息
└── loan/
    ├── gf_loan.json           女友借款流水（唯一数据源）：利率、基准天数、6 笔流水
    ├── thumbs.json            结算页凭据缩略图（shots_t）
    └── shots.json             凭据原图（点击时才加载）
```

## 数据口径

| 项目 | 说明 |
|---|---|
| 每日盈亏 | Σ 份额 × (当日收盘 − 前收)，标的 sh513870 / sh563020，份额见 `data/portfolio/positions.json` |
| 同花顺 2026 | `data/costs/baseline.json` 校准点 + 校准日之后的日盈亏合计 |
| 2022–2025 | 直接取 `data/costs/baseline.json` 各账户存量，不逐日跟踪 |
| 女友利息 | `data/loan/gf_loan.json` 流水，10% 单利、365 基准，按各段资金占用天数计息，前端按当天日期实时算 |
| 融资利息 | 2025 定值 1,500；2026 定值 50,268 + 206.11 元/天（券商实际日均，自 2026-11-17 起，含当日） |
| 融资负债 | 本金 1,957,901.83 + 日息 × 已计天数 → 担保比例 = 总市值 ÷ 负债 |
| 本人净资产 | 总市值 − 融资负债 − 女友负债（本金 + 应计利息） |
| 场内溢价 | 每日任务取自算口径 `(现价 / IOPV − 1) × 100`（腾讯行情 [3] 现价 + 官方 IOPV [78]，与 etf_report 一致；接口字段[77]仅作交叉校验）。IOPV 缺失或 ≤0 则不出溢价，不编数。写入当天记录；缺失时页面回落到 `data/portfolio/positions.json` 的手动快照 |
| 收盘价 | 腾讯不复权日K为主（与 etf_report 同源），东财日K自动兜底；均为 3 位小数、不复权，落进 `data/daily/<年>.json` 的 `closes` |
| 净收益 | 毛收益 − 女友利息 − 融资利息 |

## 日常操作

- **持仓变动**：改 `data/portfolio/positions.json`（股数 / 成本），push 即生效
- **女友借款流水**：只改 `data/loan/gf_loan.json`，三个页面都读这一份
- **同花顺校准点**：改 `data/costs/baseline.json` 的 `ths_2026_calibration`（新快照数字 + 日期）
- **补算**：默认每次回看最近 5 个交易日（`backfill=5`），缺哪天补哪天，接口日K晚生成导致的漏记会在第二天自动补回；也可用 `--backfill N` 指定天数
- **手动重跑**：再跑一次即可，按日期幂等覆盖；内容无变化则不提交

## 部署

GitHub Actions（`.github/workflows/daily.yml`）：`on: workflow_dispatch` 触发（首页打开时静默自检自动 dispatch，无按钮）跑 `job/daily_update.py`；`on: push` 触发 Pages 发布。免费版 Pages 需公开仓库。

## 本地跑

```bash
python3 job/daily_update.py            # 正常每日运行（需收盘后）
python3 job/daily_update.py --dry-run  # 只算不写不推
python3 -m http.server 8046            # 本地预览三个页面
```
