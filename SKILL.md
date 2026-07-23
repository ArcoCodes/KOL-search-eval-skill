---
name: kol searching&eval
description: >
  Use this skill for KOL/creator discovery and evaluation across YouTube, TikTok,
  Instagram, and Twitter/X. Trigger when the user wants to search creators by keyword,
  evaluate a channel/account/homepage URL, or check/update this skill's GitHub version.
allowed-tools: Bash, Read, Write
---

# KOL Evaluation

## workflow

```
人定义业务关键词
  ↓
Step 1: 搜索 (yt_search.py, yt-dlp优先 TikHub兜底)
  ↓ 去重 + 飞书查重 
Step 2: 信号采集 (youtube_data.py / tiktok_data.py / instagram_data.py / twitter_data.py)
  ↓ stdout 输出 JSON
Step 3: Agent 按 references/rough-eval-rules.md 执行粗估
  ↓ Agent 生成 /tmp/rough_judgment.json
  ↓ write_candidate.py 把KOL信息写入候选池，附具体粗估依据
  ⏸ 等待对接人接手
  ↓
Step 4: 人在候选池找到该 KOL，填写"对接人"=自己，或自行寻找优质的KOL。
  ↓ 把博主的主页URL发给自己的 agent
Step 4a: Agent 先在KOL总表和候选池里根据主页URL查看是否已经存在于系统中（check_kol_exists.py）
  ↓ 若 KOL总表已存在，则提醒用户已存在
  ↓ 若候选池已存在，则优先读取候选池中的信号快照；没有快照则重采
  ↓ 如果并不存在于系统，则先重新采集信号
Step 4b: 读取采集信号
Step 4c: Agent 按照 references/detailed-eval-rules.md 对KOL进行细估 (write_kol.py --by 对接人email/open_id)
  ↓ 写入 KOL总表(合作进度=待联系, 对接人) + 评估记录
Step 4d: 如传 --by，则飞书 IM 通知对接人 (feishu_notify.py)
```

## Subcommand Routing

Parse the skill args to determine the entry point:

1. `search` → KOL search + optional signal collection + Agent rough screening (see Search section)
2. `eval` → detailed evaluation for candidates (accepts candidate-pool URL; see Detailed Eval section)
3. `check update` / `update` / `更新 skill` → read `references/update.md` and follow the explicit update protocol
4. `check` → environment check (see Check section)
5. URL or `@handle` → signal collection + Agent rough screening (see Screen section)
   - Exception: if the user explicitly says this URL/handle comes from 候选池 or asks for "细估", route to Detailed Eval instead of rough screening.
6. Otherwise → show usage help

## Platform Detection

| Pattern | Platform | Signal Script |
|---------|----------|---------------|
| `youtube.com`| YouTube | `data_scrawl/youtube_data.py` |
| `instagram.com` | Instagram | `data_scrawl/instagram_data.py` |
| `tiktok.com` | TikTok | ``data_scrawl/tiktok_data.py`` |
| `twitter.com`, `x.com` | Twitter/X | `data_scrawl/twitter_data.py` |

**FORBIDDEN:** Playwright / HTTP raw requests / generic scrapers for social platform data. All data acquisition goes through the scripts above (yt-dlp + TikHub).

---

## Screen Pipeline (`/kol <URL>`)

**Step 2 + Step 3 combined: signal collection → Agent rough judgment → write candidate pool.**

### Step 2: Fetch Signals (automated)

Run the platform-specific script:

**YouTube:**
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 data_scrawl/youtube_data.py @handle --n 8 --comment-videos 4
```

**Instagram / TikTok / Twitter:** same pattern with `instagram.py` / `tiktok.py` / `twitter.py`.

Script output → stdout JSON.
Four-platform field inventory is documented in `references/platform-signal-collection.csv`.

**注意 stdout/stderr 分流**: youtube_data.py 的 JSON 输出在 stdout，日志在 stderr。把 stdout 保存为信号文件，不要把 stderr 混入 JSON。推荐做法:
```bash
python3 data_scrawl/youtube_data.py @handle --n 8 --comment-videos 4 > /tmp/sig.json
```

### Step 3: Agent Rough Judgment

Agent reads `/tmp/sig.json` and `references/rough-eval-rules.md`, then produces `/tmp/rough_judgment.json`.

Required JSON:
```json
{
  "候选状态": "待细估",
  "粗估得分": 85,
  "评论质量标记": "真实讨论",
  "受众辐射(推断)": "欧美为主",
  "粗估依据": "硬分85/100(ER30+粉丝15+活跃10+评论30); 评论有具体产品问题讨论; 内容与业务线相关",
  "淘汰原因": "",
  "业务线": "Renoise"
}
```

### Step 3 Write Results

**不管通过还是淘汰，所有候选 KOL 都必须写入候选池。** Agent 判断通过→`待细估`，淘汰→`已淘汰(浅筛)`。

**写入候选池：**
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 write_candidate.py --signals /tmp/sig.json --judgment /tmp/rough_judgment.json --source "discovery:xxx" --keyword "xxx"
```
write_candidate.py writes: 候选池 only. It does not compute scores or make decisions.

**粗估依据**必须写具体内容（Agent 手写硬分明细 + 关键判断）。格式:
```
硬分85/100(ER30+粉丝15+活跃10+评论30); 受众辐射: 欧美为主; 内容与 Renoise 的 AI 视频创作场景相关
```
**禁止**写"各项指标达标"这种空话。至少要包含硬分明细；如有明显风险，也应写入粗估依据。

### Output format

```
==================================================
粗估: Channel Name (@handle) [YouTube]
粉丝: 50,000 | ER: 5.20% | 均播放: 12,000
评论质量: 真实讨论 | 受众辐射: 欧美为主 | 国家: US
硬分: {'ER': 30, '粉丝': 15, '活跃': 20, '评论': 30} = 95/100
最终: ✓ 待细估 / ✗ 已淘汰(浅筛)
==================================================
```

---

## Detailed Eval (`/kol eval <URL> [--by email/open_id]`)

**Step 4: Agent根据KOL链接及已采集的信号进行细估.**

### When to use
- After a KOL passes rough screening and enters 候选池 (status=待细估)
- 对接人在候选池里把该 KOL 分给自己后，把主页URL 发给自己的 agent
- Manual eval is still allowed, but candidate-pool handoff is the default flow

### Trigger flow (Agent handoff from 候选池)

新的默认流程：
1. 人在候选池定位目标 KOL，确认 `候选状态=待细估`
2. 把 `对接人` 设成自己
3. 把该行的 `主页URL` 发给自己的 agent，并明确说"做细估并写入 KOL 总表"
4. Agent 先运行 `check_kol_exists.py <主页URL>`，然后再决定是否重采信号
5. 若返回 `exists_in_system`，提醒用户该 KOL 已存在于正式系统
6. 若返回 `candidate_snapshot` / `candidate_refetch` / `refetched`，继续细估
7. Agent 读取：
   - `业务线`
   - `对接人`
   - `主页URL`
8. Agent 运行 `/kol eval <URL> --by <对接人email/open_id>`

`对接人` 字段值用于：① 写入 KOL 总表的 `对接人` ② 细估完发飞书 IM 通知（如果传了 `--by`）。

### Step 4a: Read signals

优先运行：
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 check_kol_exists.py "<homepage_url>" --out /tmp/sig.json
```

规则：
- `exists_in_system` → 提醒用户该 KOL 已在正式系统里，不继续细估
- `candidate_snapshot` → 直接复用候选池中的信号快照
- `candidate_refetch` / `refetched` → 重新采信号，并写到 `--out`

If the user provided a 候选池 homepage URL, treat it as a detailed-eval entry point, not a rough-screening entry point.

### Step 4b: Agent Comprehensive Judgment (you do this)

Read the signal JSON + comment samples. Cross-reference `${CLAUDE_SKILL_DIR}/references/business-standards.md` to produce a judgment JSON with:

**5-Dimension Scoring** (each 1-10):
- 受众匹配 (Audience Match)
- 内容承载 (Content Capacity)
- 流量稳定 (Traffic Stability)
- 互动可信 (Engagement Credibility)
- 报价合理 (Pricing Reasonableness)

**Classification Fields:**
- **综合判断**: `建议合作` / `观望` / `放弃`
- **业务线**: `Bloome` / `Renoise`

**Required Outputs:**
- 合理报价区间 (USD, must include numbers) + 计价口径
- 一句话结论 + 判断依据

Write the judgment JSON to `/tmp/judge.json`.

**Anti-fraud signals** — check in priority order (see `references/fraud-detection.md`):
模板化重复评论 > 泛灌水占比 > 作者跨视频重复 > 频道主零回复 > 评论/点赞比异常 > 播放/订阅比

**Twitter ER note:** Twitter ER is naturally low (0.3-1% is healthy). Do NOT apply YouTube's 5% standard.

### Step 4c: Write Evaluation Card + Update Status + Notify

```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 write_kol.py --signals /tmp/sig.json --judgment /tmp/judge.json --by <对接人email_or_open_id>
```

`--by` does three things:
1. Sets KOL 总表 `合作进度` = "待联系" and `对接人` = the person
2. Sends eval report card to that person via Feishu IM (using `feishu_notify.py`)
3. Success indicator: output contains `判断卡: True ['recvXXX']` + `✅ 消息已发送`

Then aggregate to KOL Hub table:
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 sync_hub.py
```

### Report Output

```
=== KOL Evaluation Complete ===
KOL: <name> (@handle)
Platform: <platform>
Audience: <受众欧美辐射>
Scores: 受众匹配 X / 内容承载 X / 流量稳定 X / 互动可信 X / 报价合理 X
Verdict: <综合判断>
Price Range: USD X,XXX – X,XXX (<计价口径>)
Conclusion: <一句话结论>
对接人: <email/open_id> (如传 --by 则已通知)
Feishu: <record link>
```

**Currency format:** Use `USD X,XXX` — never `$X,XXX` (IM renderers eat the `$`).

---

## Search (`/kol search <keywords> [--limit N] [--after YYYY-MM] [--before YYYY-MM]`)

**Step 1 + Step 2 + Step 3: search → optional signal collection → Agent batch rough screening.**

```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 yt_search.py "<keywords>" --limit 50
```

The script:
1. **yt-dlp 优先搜索**（`ytsearch{limit}:{keyword}`，免费），如果 yt_dlp Python 模块未安装或返回空则**自动回退 TikHub**（按调用计费）
2. Groups videos by `channel_id`, extracting unique channels
3. Queries Feishu YouTube KOL明细表, marking channels already in the database
4. Outputs JSON to `/tmp/yt_search_result.json`

**yt-dlp 注意**: yt_search.py 用的是 `import yt_dlp`（Python 模块），不是 CLI。如果只装了 CLI 版 yt-dlp 而没有 `pip install yt-dlp`，会自动回退 TikHub。

**Collect signals for new channels:**
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 yt_search.py "<keywords>" --limit 50 --collect-signals --business <Bloome|Renoise|EdgeSpark>
```

With `--collect-signals`, the script runs `data_scrawl/youtube_data.py` on each new channel and saves signal JSON files under `/tmp/kol_search_signals_*`. `--auto-eval` is kept only as a deprecated alias and no longer writes to 候选池.

**After search, for each new channel with signals, run the same screening as the Screen Pipeline:**
1. Read the saved signal JSON
2. Agent applies `references/rough-eval-rules.md`
3. Agent writes `/tmp/rough_judgment.json`
4. `write_candidate.py` writes results — **所有候选都要写入候选池**（通过和淘汰都要写）

```bash
# Step 3: Agent 生成 /tmp/rough_judgment.json 后写入候选池
cd ${CLAUDE_SKILL_DIR}/scripts && python3 write_candidate.py --signals /tmp/sig.json --judgment /tmp/rough_judgment.json --source "discovery:<keywords>" --keyword "<keywords>"
```

For batch search with many channels, Agent may triage the saved signal files one by one. But **all channels selected for rough screening must end up in 候选池** with a clear status and basis.

**Dedup logic:** Channels are deduplicated by `channel_id` against the Feishu YouTube KOL明细表. A channel already in the table is marked "existing" and skipped.

---

## Feishu Architecture

**base_token:** `WEcDbjFnKa48YbsKa8qc8auQnlc`

```
KOL总表 (Hub, one person one row, tblEylVlrP1Qtrmb)
  ├─ YouTube KOL (tblzR7h4fH1y1Hkf)     ← Step 4 写入
  ├─ TikTok KOL (tblsUnmLnBVfXpEg)      ← Step 4 写入
  ├─ Instagram KOL (tblV1DXvLLoci6ZM)    ← Step 4 写入
  ├─ Twitter KOL (tbltybPG07lSIuqM)      ← Step 4 写入
  ├─ 候选池 (tblfBV6INxVDVl6X)           ← Step 3 所有粗估过的KOL(通过+淘汰)写入
  └─ 评估记录 (tblA1p25lxwHnsuV)         ← Step 4 细估后写入
```

**Table roles:**
| Table | Role | Written by |
|-------|------|-----------|
| 平台明细表 (4张) | 数据仓库 — 原始数据 + Agent补充字段 | write_kol.py |
| 候选池 | 工作台 — 所有经过粗估的 KOL（通过=待细估，淘汰=已淘汰(浅筛)） | Agent + write_candidate.py |
| 评估记录 | 判断卡 — 细估5维评分 + 报价 | write_kol.py |
| KOL总表 | Hub — 一人一行、聚合全局状态 | write_kol.py + sync_hub.py |

**Feishu write pitfalls:**
- Multi-select fields do NOT auto-create options — fetch existing options → union → write back
- Dedup key: YouTube = `channel_id`, TikTok = `sec_uid`; always check before writing
- `综合判断` only accepts `建议合作`/`观望`/`放弃` — wrong value = silent failure
- `候选状态` 只接受: `待细估`/`已通过`/`已淘汰`/ `已完成`
- `粗估依据` 禁止写空泛内容如"各项指标达标"。格式: `XX/100(ER分+粉丝分+活跃分+评论分); 关键风险: <具体结论>`
- Link field format: `[{"id":"rec..."}]`

---

## Candidate Pool Handoff (细估触发)


### 候选池表必要字段

| 字段 | 类型 | 用途 |
|------|------|------|
| 候选状态 | 单选 | 待细估 / 已通过 / 已淘汰  / 已完成 |
| 对接人 | 人员 | 谁负责跟进这个 KOL |
| 粗估得分 | 数字 | Agent 按 rough-eval-rules.md 给出的粗估分 |
| 粗估依据 | 文本 | 硬分明细 + 关键风险标记 |
| 主页URL | URL | 细估默认入口；人发给 agent 的就是这个 |
| 平台内ID | 文本 | 候选池内去重和兜底定位 |
| 业务线 | 多选 | Bloome/Renoise/EdgeSpark |
| 采集信号JSON | 长文本 | 可选；若字段存在，write_candidate.py 会写入信号快照供 Step 4 复用 |

### 人的操作

1. 在候选池找到目标 KOL
2. 把 `对接人` 设成自己
3. 把该行 `主页URL` 发给自己的 agent
4. 告诉 agent 这是候选池里的 KOL，需要继续细估并写入 KOL 总表

### Agent 的操作

1. 把这个 URL 视为 Step 4 入口，而不是 Step 2+3 的粗估入口
2. 先运行 `check_kol_exists.py` 做系统查重和信号准备
3. 再回候选池读该记录，拿到 `业务线` 和 `对接人`
4. 读取 `sig.json`（候选池快照或重新采集）
5. 产出 `/tmp/judge.json`
6. 执行 `write_kol.py --by <对接人email/open_id>`，把结果写入平台明细 / 评估记录 / KOL 总表
7. 最后执行 `sync_hub.py`

---

## Feishu IM Notification Setup

`feishu_notify.py` 用已有自建应用发消息给个人。

### Prerequisites

1. 在 `scripts/.env` 中配置：
```
FEISHU_APP_ID=cli_xxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxx
```

2. 自建应用需开通权限：
   - `im:message:send_v2`（发送消息）
   - `contact:user.id:readonly`（email → open_id 解析）

3. 测试发送：
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 feishu_notify.py --to user@example.com --body "测试消息"
```

---

## Check (`/kol check`)

Verify dependencies and report status:

```bash
echo "=== KOL Skill Environment Check ==="
command -v python3   && echo "✓ python3 $(python3 --version 2>&1)" || echo "✗ python3 not found"
command -v yt-dlp    && echo "✓ yt-dlp $(yt-dlp --version)"       || echo "✗ yt-dlp not found — brew install yt-dlp"
command -v lark-cli  && echo "✓ lark-cli installed"                || echo "✗ lark-cli not found — npm install -g lark-cli"
python3 -c "import requests; print('✓ requests installed')" 2>/dev/null || echo "✗ requests not found — pip3 install requests"
python3 -c "import yt_dlp; print('✓ yt_dlp Python module installed')" 2>/dev/null || echo "⚠ yt_dlp Python module not found — pip3 install yt-dlp (搜索会回退TikHub)"
test -f "${CLAUDE_SKILL_DIR}/scripts/.env" && echo "✓ .env file exists" || echo "✗ .env not found in scripts/"
grep -q "TIKHUB_API_KEY" "${CLAUDE_SKILL_DIR}/scripts/.env" 2>/dev/null && echo "✓ TIKHUB_API_KEY configured" || echo "✗ TIKHUB_API_KEY not set in scripts/.env"
grep -q "FEISHU_APP_ID" "${CLAUDE_SKILL_DIR}/scripts/.env" 2>/dev/null && echo "✓ FEISHU_APP_ID configured" || echo "✗ FEISHU_APP_ID not set — 细估通知不可用"
grep -q "FEISHU_APP_SECRET" "${CLAUDE_SKILL_DIR}/scripts/.env" 2>/dev/null && echo "✓ FEISHU_APP_SECRET configured" || echo "✗ FEISHU_APP_SECRET not set — 细估通知不可用"
```

Also verify Feishu access:
```bash
lark-cli api GET /open-apis/bitable/v1/apps/WEcDbjFnKa48YbsKa8qc8auQnlc/tables --jq '.data.total'
```

## Update (`/kol check update` or `/kol update`)

Do not check for updates during normal KOL workflows. Only when the user
explicitly asks to check or install updates, read `references/update.md` and
follow that protocol.

## Reference Documents

| File | Purpose |
|------|---------|
| `references/business-standards.md` | Bloome/Renoise evaluation criteria, ER baselines, Twitter weight |
| `references/methodology.md` | Full methodology: ER calc, anti-fraud tiers, pricing formula, BLUF format |
| `references/tag-taxonomy.md` | Content tag controlled vocabulary (11 categories) |
| `references/fraud-detection.md` | Correlation-based fraud detection method (with Python script) |
| `references/update.md` | Manual check/update protocol for GitHub-distributed skill versions |
| `README.md` | Environment setup, dependencies, usage, and repository overview |
