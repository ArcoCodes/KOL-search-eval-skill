# KOL-search-eval-skill

[English](README.md) | **中文**

KOL-search-eval-skill 是一个用于创作者发现、信号采集、粗估筛选和细估评价的 Codex skill，支持 YouTube、TikTok、Instagram 和 Twitter/X 四个平台。

这套流程围绕一个实际目标：找到真正能帮助获客的创作者，而不只是粉丝数好看的账号。它结合了平台数据、评论质量检测、受众地区推断、报价估算和飞书/多维表格回写。

## 功能概览

- 按关键词搜索创作者，以 YouTube 发现为起点
- 通过专用脚本采集各平台信号
- 粗估阶段筛查注水/买量、活跃度、互动率和受众匹配
- 将合格或淘汰的创作者写入飞书候选池
- 细估时复用候选池中的信号快照
- 写入细估记录、KOL 总表，可选飞书 IM 通知对接人

## 工作流程

```text
搜索
  -> 信号采集
  -> 粗估筛选
  -> 候选池
  -> 人工分配对接人
  -> 细估评价
  -> KOL 总表 + 评估记录
```

常用入口：

```bash
/kol search "AI video tools"
/kol https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxx
/kol eval https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxx
/kol check
```

只有通过 `/kol search ...` 发现的 KOL 才会走粗估和候选池写入流程。直接给主页 URL 视为细估入口，不写候选池。

## 目录结构

| 路径 | 用途 |
|------|------|
| `SKILL.md` | Codex skill 指令和路由逻辑 |
| `scripts/yt_search.py` | YouTube 创作者搜索 |
| `scripts/data_scrawl/` | YouTube、TikTok、Instagram、Twitter/X 信号采集脚本 |
| `scripts/write_candidate.py` | 粗估后写入候选池 |
| `scripts/check_kol_exists.py` | 细估前查询 KOL/候选池是否已存在 |
| `scripts/write_kol.py` | 细估结果写入 |
| `scripts/feishu_notify.py` | 飞书 IM 通知（可选） |
| `references/` | 评估规则、方法论、schema 说明、标签体系、反欺诈参考 |
| `docs/kol-reports/` | KOL 报告示例 |

## 依赖

| 依赖 | 安装方式 | 用途 |
|------|---------|------|
| Python 3 | 系统自带或 `brew install python` | 评估脚本运行环境 |
| yt-dlp | `brew install yt-dlp` | YouTube 数据抓取（主力） |
| lark-cli | `npm install -g lark-cli` | 飞书多维表格读写 |
| requests | `pip3 install requests` | 脚本中的 HTTP 请求 |
| yt-dlp Python 模块 | `pip3 install yt-dlp` | 部分采集流程的 Python import 路径（可选） |

## 配置

创建 `scripts/.env`：

```dotenv
TIKHUB_API_KEY=your_api_key_here
FEISHU_APP_ID=cli_xxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxx
```

环境变量也可以直接在 shell 中 export。脚本优先读 shell 环境变量，找不到时回退到 `scripts/.env`。

| 变量 | 用于 | 说明 |
|------|------|------|
| `TIKHUB_API_KEY` | TikTok、Instagram、Twitter/X 及 YouTube 兜底 | YouTube 优先用 yt-dlp（免费）；TikHub 在限流时或非 YouTube 平台使用 |
| `FEISHU_APP_ID` | 飞书 IM 通知和 app-token 流程 | `scripts/feishu_notify.py` 需要 |
| `FEISHU_APP_SECRET` | 飞书 IM 通知和 app-token 流程 | `scripts/feishu_notify.py` 需要 |

不要提交 `scripts/.env` 或其他 `.env` 文件。本仓库的 `.gitignore` 默认排除了环境文件。

## TikHub 计费说明

- YouTube：yt-dlp 是主力数据源，免费。TikHub 仅在限流或需要额外数据时作为兜底。
- Instagram、TikTok、Twitter/X：TikHub 是必需数据源，API 调用会计费。
- 脚本内置了约 8 RPS 的限流控制。如果未来批量任务使用多进程，需要加共享限流器。

## 验证

运行：

```bash
/kol check
```

或手动检查环境：

```bash
command -v python3 && python3 --version
command -v yt-dlp && yt-dlp --version
command -v lark-cli && echo "lark-cli OK"
python3 -c "import requests; print('requests OK')"
python3 -c "import yt_dlp; print('yt_dlp module OK')"
grep -q TIKHUB_API_KEY scripts/.env && echo "TIKHUB_API_KEY configured"
grep -q FEISHU_APP_ID scripts/.env && echo "FEISHU_APP_ID configured"
grep -q FEISHU_APP_SECRET scripts/.env && echo "FEISHU_APP_SECRET configured"
```

脚本 import 冒烟测试：

```bash
cd scripts
python3 -c "import tikhub; print('tikhub OK')"
python3 data_scrawl/youtube_data.py --help
```

飞书连通性检查：

```bash
lark-cli api GET /open-apis/bitable/v1/apps/WEcDbjFnKa48YbsKa8qc8auQnlc/tables --jq '.data.total'
```

## 常见问题

- `yt-dlp` 报错：用 `brew upgrade yt-dlp` 更新。YouTube 经常变动接口。
- YouTube 要求登录或人机验证：暂停高频评论抓取，或在合适时使用 `yt-dlp --cookies-from-browser chrome`。
- `lark-cli` 认证过期：重新运行 `lark-cli` 刷新凭证。
- TikHub 返回 403：检查 API key 有效性和 TikHub 后台余额。
- TikTok/Instagram/Twitter 采集直接失败：确认 `scripts/.env` 或 shell 环境中配置了 `TIKHUB_API_KEY`。

## 参考文档

| 文件 | 用途 |
|------|------|
| `references/process.md` | 端到端 KOL 评估和写入流程 |
| `references/business-standards.md` | 业务线评分标准和 CPM 参考 |
| `references/methodology.md` | 评估方法论、反欺诈信号、报价逻辑 |
| `references/rough-eval-rules.md` | 粗估筛选规则 |
| `references/detailed-eval-rules.md` | 细估评价规则 |
| `references/tag-taxonomy.md` | 内容标签受控词表 |
| `references/fraud-detection.md` | 注水检测方法和相关性校验 |
| `references/DB-schema.md` | 飞书多维表格 schema 说明 |
