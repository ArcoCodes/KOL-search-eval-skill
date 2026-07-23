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
Step 4: 人给出 KOL 主页URL（来自候选池或自行发现都可以）。
  ↓ 把博主的主页URL发给自己的 agent
Step 4a: Agent 先在KOL总表和候选池里根据主页URL查看是否已经存在于系统中（check_kol_exists.py）
  ↓ 若 KOL总表已存在，则提醒用户已存在
  ↓ 若候选池已存在，则把候选状态改成"已通过"，带候选池全量行信息进入细估；有信号快照则复用，没有则重采
  ↓ 若 KOL总表和候选池都不存在，则采集信号后直接进入细估，不写候选池
Step 4b: 读取采集信号 + 候选池元信息（如果存在）
Step 4c: Agent 按照 references/detailed-eval-rules.md 对KOL进行细估 (write_kol.py --by 对接人email/open_id)
  ↓ 写入 KOL总表(合作进度=待联系, 对接人) + 评估记录
```

## Subcommand Routing

Parse the skill args to determine the entry point:

1. `search` → KOL search + optional signal collection + Agent rough screening (see Search section)
2. `eval` → detailed evaluation for candidates (accepts candidate-pool URL; see Detailed Eval section)
3. `check update` / `update` / `更新 skill` → read `references/update.md` and follow the explicit update protocol
4. `check` → environment check (see Check section)
5. Homepage URL → Detailed Eval by default. Always run `check_kol_exists.py` first; do not rough-screen or write the candidate pool.
6. Non-URL account identifiers are unsupported. Ask the user for the KOL homepage URL.
7. Otherwise → show usage help

## Platform Detection

| Pattern | Platform | Signal Script |
|---------|----------|---------------|
| `youtube.com`| YouTube | `data_scrawl/youtube_data.py` |
| `instagram.com` | Instagram | `data_scrawl/instagram_data.py` |
| `tiktok.com` | TikTok | `data_scrawl/tiktok_data.py` |
| `twitter.com`, `x.com` | Twitter/X | `data_scrawl/twitter_data.py` |

**FORBIDDEN:** Playwright / HTTP raw requests / generic scrapers for social platform data. All data acquisition goes through the scripts above (yt-dlp + TikHub).

---

## Rough Screening Pipeline (search results only)

**Step 2 + Step 3 combined: signal collection → Agent rough judgment → write candidate pool.**

Use this pipeline only for KOLs discovered through `/kol search ...`.

Do not use this pipeline for a homepage URL directly sent by the user. Direct homepage URLs are Step 4 detailed-eval entry points.

### Step 2: Fetch Signals (automated)

Run the platform-specific script:

**YouTube:**
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 data_scrawl/youtube_data.py "<youtube_homepage_url>" --n 8 --comment-videos 4
```

**Instagram / TikTok / Twitter:** same pattern with `data_scrawl/instagram_data.py` / `data_scrawl/tiktok_data.py` / `data_scrawl/twitter_data.py`.

Script output → stdout JSON.
Four-platform field inventory is documented in `references/platform-signal-collection.csv`.

**注意 stdout/stderr 分流**: youtube_data.py 的 JSON 输出在 stdout，日志在 stderr。把 stdout 保存为信号文件，不要把 stderr 混入 JSON。推荐做法:
```bash
python3 data_scrawl/youtube_data.py "<homepage_url>" --n 8 --comment-videos 4 > /tmp/sig.json
```

### Step 3: Agent Rough Judgment

Agent reads `/tmp/sig.json` and `references/rough-eval-rules.md`, then produces `/tmp/rough_judgment.json`.

Required JSON:
```json
{
  "候选状态": "待细估",
  "粗估得分": 75,
  "评论质量标记": "真实讨论",
  "受众辐射(推断)": "欧美为主",
  "粗估依据": "互动数据正常(点赞率3.2%, 赞评比2.1%, 赞评相关0.82); 5.2万粉均播1.2万, 粉播比合理; 受众以欧美为主(评论语言85%英语); 内容围绕AI视频生成/图像编辑，与Renoise场景相关; 评论有具体产品使用讨论，未见明显灌水; 风险: 更新频率偏低(月均2条)",
  "淘汰原因": "",
  "业务线": "Renoise"
}
```

`粗估得分` 是 Agent 的综合判断分（0-100），不是维度分加总。Agent 看完信号后自主评估，重点筛注水/买量号。详见 `references/rough-eval-rules.md`。

### Step 3 Write Results

**不管通过还是淘汰，所有从 search 结果进入粗估的 KOL 都必须写入候选池。** Agent 判断通过→`待细估`，淘汰→`已淘汰(浅筛)`。

**写入候选池：**
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 write_candidate.py --from-search --signals /tmp/sig.json --judgment /tmp/rough_judgment.json --source "discovery:xxx" --keyword "xxx"
```
write_candidate.py writes: 候选池 only. It does not compute scores or make decisions.

`write_candidate.py` has a hard guard: it only accepts search-discovered KOLs with `--from-search --source "discovery:<keywords>" --keyword "<keywords>"`. If the user directly provided a homepage URL, do not call this script.

**粗估依据**必须写具体内容，示例:
```
互动数据正常(点赞率3.2%, 赞评比2.1%, 赞评相关0.82); 5.2万粉均播1.2万, 粉播比合理; 受众以欧美为主(评论语言85%英语); 内容围绕AI视频生成/图像编辑，与Renoise场景相关; 评论有具体产品使用讨论，未见明显灌水; 风险: 更新频率偏低(月均2条)
```
**禁止**写"各项指标达标"这种空话。要包含互动数据是否正常（注水风险判断）、粉播关系、受众判断、内容相关性、关键数据及风险点。

### 粗估输出

Agent 用自然语言向用户汇报粗估结论，不要求固定格式。内容应涵盖：KOL 名称、平台、关键数据（粉丝数/ER/均播放）、评论质量判断、受众判断、最终结论（待细估/已淘汰）及主要理由。用对方能直接理解的话说清楚，避免堆砌缩写和内部术语。

---

## Detailed Eval (`/kol eval <URL> [--by email/open_id]`)

**Step 4: Agent根据KOL链接及已采集的信号进行细估**

### When to use
- Whenever the user provides a KOL homepage URL
- After a KOL passes rough screening and enters 候选池 (status=待细估)
- 对接人在候选池里把该 KOL 分给自己后，把主页URL 发给自己的 agent
- Manual eval for a new homepage URL is allowed and should skip the candidate pool

### Trigger flow (homepage URL handoff)

新的默认流程：
1. 用户给出 KOL 主页URL
2. Agent 先运行 `check_kol_exists.py <主页URL>`，同时查 KOL总表/平台明细和候选池
3. 若返回 `exists_in_system`，提醒用户该 KOL 已存在于正式系统，不继续细估
4. 若返回 `candidate_snapshot` / `candidate_refetch`：候选池已命中，脚本已把 `候选状态` 更新为 `已通过`；继续细估
5. 若返回 `refetched`：KOL总表和候选池都不存在，脚本已采集信号；继续细估，细估完成后只写 KOL总表/平台明细/评估记录，不写候选池
6. Agent 读取：
   - `业务线`
   - `对接人`
   - `主页URL`
   - 候选池命中时的全部候选池字段（`candidate_pool.fields`）
7. Agent 运行 `/kol eval <URL> --by <对接人email/open_id>`

`对接人` 字段值用于写入 KOL 总表的 `对接人`。

### Step 4a: Read signals

优先运行：
```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 check_kol_exists.py "<homepage_url>" --out /tmp/sig.json --meta-out /tmp/kol_lookup.json
```

规则：
- `exists_in_system` → 提醒用户该 KOL 已在正式系统里，不继续细估
- `candidate_snapshot` → 候选池命中，候选状态已改为 `已通过`；直接复用候选池中的信号快照，并读取 `/tmp/kol_lookup.json` 的 `candidate_pool.fields`
- `candidate_refetch` → 候选池命中，候选状态已改为 `已通过`；读取 `/tmp/kol_lookup.json` 的 `candidate_pool.fields`，重新采信号，并写到 `--out`
- `refetched` → KOL总表和候选池都不存在；重新采信号并进入细估，细估后写入 KOL总表/平台明细/评估记录，不调用 `write_candidate.py`

If the user provided any homepage URL, treat it as a detailed-eval entry point, not a rough-screening entry point.

### Step 4b: Agent Comprehensive Judgment (you do this)

Read the signal JSON + comment samples. Cross-reference `${CLAUDE_SKILL_DIR}/references/business-standards.md` to produce a judgment JSON with:

**judge.json 完整 schema**（`write_kol.py` 按此读取，缺字段会导致报告/落库缺项）：

```json
{
  "业务线": "Bloome | Renoise",
  "受众欧美辐射": "欧美为主 | 日本为主 | 巴西/葡语拉美为主 | 分散无主导 | 非欧美为主 | 未知/待核实",
  "推断受众地区": "自然语言描述，如'英语国家为主(评论100%英语)'",
  "评论质量标记": "真实讨论 | 一般 | 严重灌水/疑似养号",
  "内容语言": "en / zh / ja / ...",
  "题材_LLM": "Agent 对频道题材的英文概括",
  "调性_LLM": "Agent 对频道调性的概括",
  "内容题材": ["多选，如 AI编程·开发、AI视频"],
  "提及工具": ["多选，如 Claude Code、Runway"],
  "scores": {
    "受众匹配": "1-10",
    "内容承载": "1-10",
    "流量稳定": "1-10",
    "互动可信": "1-10",
    "报价合理": "1-10"
  },
  "综合判断": "建议合作 | 观望 | 放弃",
  "判断依据": "完整判断理由，含各维度关键论据",
  "一句话": "一句话结论，用于报告摘要",
  "有效播放": "中位播放数(数字)",
  "合理报价区间USD": "如 flat/USD 1,000-2,000",
  "计价口径": "报价推算依据说明",
  "状态": "未合作",
  "备注": "可选",
  "频道评估": "一句话摘要，写法参考 detailed-eval-rules.md 第一维度",
  "受众结构": "一句话摘要，写法参考 detailed-eval-rules.md 第二维度",
  "流量稳定性": "一句话摘要，写法参考 detailed-eval-rules.md 第三维度",
  "互动真实性": "一句话摘要，写法参考 detailed-eval-rules.md 第四维度",
  "内容匹配度": "一句话摘要，写法参考 detailed-eval-rules.md 第五维度"
}
```

**注意**：`scores` 里的 5 个数字评分写入评估记录表，底部 5 个文本摘要（频道评估/受众结构/流量稳定性/互动真实性/内容匹配度）写入 KOL 总表，两者必须都填。单选字段值必须严格匹配上述枚举，否则飞书整条静默写入失败。

Write the judgment JSON to `/tmp/judge.json`.

**Anti-fraud signals** — check in priority order (see `references/fraud-detection.md`):
模板化重复评论 > 泛灌水占比 > 作者跨视频重复 > 频道主零回复 > 评论/点赞比异常 > 播放/订阅比

**Twitter ER note:** Twitter ER is naturally low (0.3-1% is healthy). Do NOT apply YouTube's 5% standard.

### Step 4c: Write Evaluation Card + Update Status

```bash
cd ${CLAUDE_SKILL_DIR}/scripts && python3 write_kol.py --signals /tmp/sig.json --judgment /tmp/judge.json --by <对接人email_or_open_id>
```

`--by` sets KOL 总表 `合作进度` = "待联系" and `对接人` = the person.

### 细估输出

Agent 用自然语言向用户汇报细估结论，不要求固定格式。内容应涵盖：KOL 名称、平台、五维评分、综合判断（建议合作/观望/放弃）、合理报价区间、一句话结论、对接人及飞书记录链接。

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

**After search, for each new channel with signals, run the Rough Screening Pipeline:**
1. Read the saved signal JSON
2. Agent applies `references/rough-eval-rules.md`
3. Agent writes `/tmp/rough_judgment.json`
4. `write_candidate.py` writes results — **所有候选都要写入候选池**（通过和淘汰都要写）

```bash
# Step 3: Agent 生成 /tmp/rough_judgment.json 后写入候选池
cd ${CLAUDE_SKILL_DIR}/scripts && python3 write_candidate.py --from-search --signals /tmp/sig.json --judgment /tmp/rough_judgment.json --source "discovery:<keywords>" --keyword "<keywords>"
```

For batch search with many channels, Agent may triage the saved signal files one by one. But **all search-discovered channels selected for rough screening must end up in 候选池** with a clear status and basis.

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
| KOL总表 | Hub — 一人一行、聚合全局状态 | write_kol.py |

**Feishu write pitfalls:**
- Multi-select fields do NOT auto-create options — fetch existing options → union → write back
- Dedup key: YouTube = `channel_id`, TikTok = `sec_uid`; always check before writing
- `综合判断` only accepts `建议合作`/`观望`/`放弃` — wrong value = silent failure
- `候选状态` 只接受: `待细估`/`已通过`/`已淘汰`/`已完成`
- `粗估依据` 禁止写空泛内容如"各项指标达标"。要包含互动数据判断（点赞率/赞评比/相关性）、粉播关系、关键风险点
- Link field format: `[{"id":"rec..."}]`

---

## 候选池字段说明

| 字段 | 类型 | 用途 |
|------|------|------|
| 候选状态 | 单选 | 待细估/已通过/已淘汰/已完成 |
| 对接人 | 人员 | 谁负责跟进这个 KOL |
| 粗估得分 | 数字 | Agent 综合判断分（0-100），重点判断注水/买量风险 |
| 粗估依据 | 文本 | 互动数据判断 + 关键风险标记 |
| 主页URL | URL | 细估默认入口；人发给 agent 的就是这个 |
| 平台内ID | 文本 | 候选池内去重和兜底定位 |
| 业务线 | 多选 | Bloome/Renoise/EdgeSpark |
| 采集信号JSON | 长文本 | 可选；若字段存在，write_candidate.py 会写入信号快照供 Step 4 复用 |

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
