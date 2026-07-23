# KOL 评估落库流程

> 四步流水线：搜索 → 信号采集 → 粗估(Agent) → 细估(Agent+人工)

## 触发

- `/kol <主页URL>` → Step 4（先查 KOL总表/候选池，再直接细估）
- `/kol search <keywords>` → Step 1 + Step 2 + Step 3（搜索 + 批量粗估）
- `/kol eval <主页URL>` → Step 4（细估，需 Agent 判断；不写候选池）
- 非 URL 账号标识不支持；要求用户提供 KOL 主页URL

## 流程总览

```
搜索(skill)  →  信号采集(脚本)  →  粗估(Agent)+候选池写入  →  细估(Agent+人工)
  Step 1           Step 2              Step 3               Step 4
                                        │                      │
                                   ┌────┴────┐                │
                                [通过]     [淘汰]              │
                                   │     标记原因              │
                                   ▼                           │
                              候选池(待细估)                   │
                                   │                           │
                                   ▼                           ▼
                           对接人设为自己 + 发主页链接给 agent 评估记录(判断卡)
                                                               │
                                                               ▼
                                                          KOL总表(聚合)
```

---

## Step 1：搜索（skill 调参数）

**执行**：
```bash
python3 yt_search.py "<keywords>" --limit 50
```

支持参数：`--limit`（视频数）、`--max-pages`（翻页数）、`--collect-signals`（自动采集信号给 Agent 粗估）

**产出**：`/tmp/yt_search_result.json` — 新频道列表 + 已有频道列表

**不涉及任何飞书写入**（仅查 YouTube KOL明细表做去重）

---

## Step 2：信号采集（脚本自动）

**执行**：按平台路由

| 平台 | 命令 |
|------|------|
| YouTube | `python3 data_scrawl/youtube_data.py "<youtube_homepage_url>" --n 8 --comment-videos 4` |
| Instagram | `python3 data_scrawl/instagram_data.py analyze "<instagram_homepage_url>"` |
| TikTok | `python3 data_scrawl/tiktok_data.py analyze "<tiktok_homepage_url>"` |
| Twitter/X | `python3 data_scrawl/twitter_data.py analyze "<twitter_homepage_url>"` |

**数据源**：yt-dlp（免费优先）→ TikHub（限流兜底）

**产出**：stdout JSON（推荐保存为 `/tmp/sig.json`）；如进入细估入口，也可由 `check_kol_exists.py --out /tmp/sig.json` 生成临时文件

**边界**：Step 2 只作为 search 后批量粗估或 Step 4 细估的数据准备；用户必须提供主页URL。

**不涉及任何飞书写入**

---

## Step 3：粗估（Agent + `write_candidate.py`）

**只用于 `/kol search ...` 找到的 KOL。** 用户直接给主页URL时，不走 Step 3，不调用 `write_candidate.py`。

**执行**：
```bash
python3 data_scrawl/youtube_data.py "<homepage_url>" --n 8 --comment-videos 4 > /tmp/sig.json
```

Agent 读取 `/tmp/sig.json` 与 `references/rough-eval-rules.md` 后，写出 `/tmp/rough_judgment.json`，再执行：

```bash
python3 write_candidate.py --from-search --signals /tmp/sig.json --judgment /tmp/rough_judgment.json --source "discovery:AI video" --keyword "AI coding"
```

`write_candidate.py` 会强制校验 `--from-search`、`source=discovery:*` 和非空 `--keyword`。用户直接发主页URL时，即使误调用该脚本，也应失败，不允许写候选池。

### 3.1 浅判断自动推导

Agent 从 sig.json 的评论分析数据推导：

| 字段 | 推导规则 |
|------|---------|
| 评论质量标记 | 模板化重复 ≥15% 或 泛灌水 ≥40% → 严重灌水；泛灌水 ≥20% → 一般；否则 → 真实讨论 |
| 受众辐射(推断) | 评论语言英文 ≥50% → 欧美为主；日文 ≥40% → 日本为主；葡文 ≥40% → 巴西/葡语拉美为主 |

### 3.2 硬标准粗估打分 (0-100)

| 维度 | 分值 | YouTube | TikTok | Instagram | Twitter |
|------|------|---------|--------|-----------|---------|
| ER | 0-30 | ≥2% | ≥3% | ≥1% | ≥0.3% |
| 粉丝数 | 0-20 | ≥1K | ≥1K | ≥1K | ≥500 |
| 活跃度 | 0-20 | ≤90天 | ≤90天 | ≤90天 | ≤90天 |
| 评论质量 | 0-30 | 非严重灌水 | 同左 | 同左 | 同左 |

**一票否决**：评论质量=严重灌水/疑似养号 → 无论得分直接淘汰

**通过线**：≥60 分

### 3.3 写入候选池

| 表 | table_id | 操作 |
|----|----------|------|
| 候选池 | `tblfBV6INxVDVl6X` | 新建/更新（按平台内ID去重） |

写入规则：
- 通过 → `候选状态=待细估`
- 淘汰 → `候选状态=已淘汰(浅筛)`

候选池独立存储关键字段（名称/主页URL/平台内ID/粉丝/ER/均播放/受众辐射/评论质量/粗估得分/粗估依据）。
如果候选池里存在 `采集信号JSON`（或兼容字段 `信号JSON` / `信号快照JSON`），`write_candidate.py` 会把 Step 2 的整包 stdout JSON 一并写入，供 Step 4 直接复用。

### 3.4 Step 3 不做的事

- 不写平台明细表
- 不写 KOL总表
- 不做 5 维细估

**成功标志**：`write_candidate.py` 输出 `ok: true`、`record_id`、`status`

---

## Step 4：细估（`/kol <主页URL>` 或 `/kol eval <主页URL>`，Agent + 人工）

**前提**：用户给出 KOL 主页URL。候选池命中不是必需条件；新发现的 URL 也直接进入细估。

### 4.0 触发方式

默认不再走飞书按钮 / webhook / EdgeSpark 服务触发。

新的默认方式是：
1. 用户把 KOL 主页URL 发给 agent
2. agent 先运行 `check_kol_exists.py` 检查 KOL总表/平台明细和候选池
3. 如果已在 KOL总表/正式系统中，提醒用户已存在，不继续细估
4. 如果在候选池中，脚本把 `候选状态` 改成 `已通过`，并把候选池该行所有字段带入细估
5. 如果 KOL总表和候选池都没有，脚本从采集信息开始，然后立刻进入细估；细估后写入 KOL总表/平台明细/评估记录，不写候选池

推荐执行：
```bash
python3 check_kol_exists.py "<homepage_url>" --out /tmp/sig.json --meta-out /tmp/kol_lookup.json
```

### 4.1 Agent 综合判断

**输入**：`check_kol_exists.py` 产出的信号（候选池快照或重新采集）+ 候选池命中时的 `/tmp/kol_lookup.json` + `references/business-standards.md`

**产出**：`/tmp/judge.json` — 包含：
- 5 维评分（受众匹配 / 内容承载 / 流量稳定 / 互动可信 / 报价合理，各 1-10）
- 综合判断（建议合作 / 观望 / 放弃）
- 合理报价区间 USD + 计价口径
- 判断依据

### 4.2 写入评估记录

**执行**：
```bash
python3 write_kol.py --signals /tmp/sig.json --judgment /tmp/judge.json --by <对接人email/open_id>
```

| 表 | table_id | 操作 |
|----|----------|------|
| 平台明细表 | 对应平台 | 新建或更新：补充客观数据 + Agent 判断字段 |
| KOL总表 | `tblEylVlrP1Qtrmb` | 新建或挂主体 |
| 评估记录 | `tblA1p25lxwHnsuV` | 新建判断卡：关联主体、5维评分、综合判断、报价 |

### 4.3 聚合回填

```bash
python3 sync_hub.py
```

从评估记录聚合 → KOL总表回填综合判断、情况说明、状态更新时间

**成功标志**：输出 `判断卡: True ['recvXXX']`

---

## 表交互总览

```
Step 1              Step 2              Step 3                         Step 4
搜索                信号采集            Agent + write_candidate.py      write_kol.py + sync_hub.py
(查飞书去重)        (无飞书交互)        (粗估+候选池)                  (细估落库)
│                                       │                              │
▼                                       ▼                              ▼
┌─────────────┐                 ┌──────────────┐               ┌──────────────┐
│ YouTube KOL │                 │ 候选池        │               │ 平台明细表    │
│ (READ only) │                 │ WRITE 粗估结果│               │ WRITE 新建/补充│
└─────────────┘                 │ + 浅判断      │               │ 内容题材等   │
                                │ + 粗估状态    │               └──────┬───────┘
                                └──────┬───────┘                      │
                                       │                              ▼
                                 ┌─────┴─────┐                ┌──────────────┐
                              [待细估]   [已淘汰]              │ 评估记录表    │
                                 │                             │ WRITE 判断卡 │
                                 ▼                             └──────┬───────┘
                          ┌──────────────┐                            │
                          │ 人分配对接人   │                            ▼
                          │ 并发主页链接   │                     ┌──────────────┐
                          └──────┬───────┘                     │ KOL总表       │
                                 │                             │ WRITE 建主体  │
                                 ▼                             │ + 聚合回填    │
                          ┌──────────────┐                     └──────────────┘
                          │ agent 进入细估 │
                          └──────────────┘
```

## 未涉及的表

| 表 | 为什么不涉及 |
|----|-------------|
| 合作批次 | 属于建联/合作阶段 |
| 邮件往来 | 属于邮件沟通阶段 |
| 沟通Case库 | 属于邮件自主学习 |
| KOL 已上线 | 属于上线归因阶段 |
| 指标快照表 | 时序快照 |
| KOL合作费用标准表 | CPM 标准已内联到 business-standards.md |
| 业务线评估标准表 | business-standards.md 是离线同步副本 |
