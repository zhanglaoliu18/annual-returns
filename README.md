# annual-returns · 年度收益总览（独立版）

数据与展示分离的年度收益追踪：

- **数据层**：`data/` 按年归档 JSON（`2026.json`…），每日一只 ETF 盈亏一条记录，git 留痕
- **展示层**：`site/index.html` 静态页，打开时读全部 JSON 现算现渲染
- **任务层**：`job/daily_update.py` 每天 15:10 拉收盘价 → 追加记录 → commit + push

## 数据口径

| 项目 | 说明 |
|---|---|
| 每日盈亏 | Σ 份额 × (当日收盘 − 前收)，标的 sh513870 / sh563020，份额见 `positions.json` |
| 同花顺 2026 | `baseline.json` 校准点（2026-11-18 收盘后快照 173,617）+ 校准日之后的日盈亏合计 |
| 2022–2025 | 直接取 `baseline.json` 各账户存量，不逐日跟踪 |
| 女友利息 | 10% 单利、365 基准，按各段资金占用天数计息，前端按当天日期实时算 |
| 融资利息 | 2025 定值 1,500；2026 定值 50,268 + 206.67 元/天（自 2026-11-18 起，含当日） |
| 净收益 | 毛收益 − 女友利息 − 融资利息 |

## 日常操作

- **股票/持仓变动**：改 `positions.json`（份额）或 `baseline.json` 的校准点（给新快照数字 + 日期），push 即生效
- **补算**：`python3 job/daily_update.py --backfill N`（补最近 N 个交易日）
- **手动重跑**：直接再跑一次即可，按日期幂等覆盖

## 部署（Cloady）

1. Cloady 控制台 → 新建应用 → 连接本 GitHub 仓库（`zhanglaoliu18/annual-returns`）
2. 端口设 `8000`（容器内是 `python3 -m http.server`，Dockerfile 已带 cron + 上海时区）
3. 环境变量加 `GITHUB_TOKEN`：一个有本仓库 push 权限的 Fine-grained PAT（Contents: Read and write），每日任务用它自动 commit + push
4. push 代码后 Cloady 自动重新构建；数据文件每天被 bot push 更新后也会触发重建，页面始终最新

## 本地跑

```bash
python3 job/daily_update.py            # 正常每日运行（需收盘后）
python3 job/daily_update.py --dry-run  # 只算不写不推
```
