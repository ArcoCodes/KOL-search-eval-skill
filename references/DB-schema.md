# Candidate Pool DB Schema

> Source of truth: `lark-cli base +field-list --base-token WEcDbjFnKa48YbsKa8qc8auQnlc --table-id tblfBV6INxVDVl6X --as user`
>
> Read on: 2026-07-23
> Table: 候选池 (`tblfBV6INxVDVl6X`)
> Note: `@handle` was manually removed from the live table after the initial schema read on 2026-07-23.

## Summary

- Total fields: `22` after removing `@handle`
- Current table role: Step 3 rough-screening workbench + Step 4 human handoff entry
- Important mismatch with current docs/code:
  - `业务线` only has `Bloome` / `Renoise`; `EdgeSpark` is missing
  - There is no `采集信号JSON` / `信号JSON` / `信号快照JSON` field in the live table yet, so `write_candidate.py` cannot currently persist the full signal snapshot

## Live Field Schema

| # | Field | Type | Options / Link | Notes |
|---|---|---|---|---|
| 1 | `关联主体` | `link` | link → `tblEylVlrP1Qtrmb` | Linked KOL hub record |
| 2 | `近期均播放` | `number` | precision `0`, thousands separator | Recent average views / plays |
| 3 | `评论质量标记` | `select` | `真实讨论` / `一般` / `严重灌水/疑似养号` | Rough-screen derived |
| 4 | `创作者国家(自报)` | `text` | - | Description says this is self-reported / platform-exposed only |
| 5 | `账号名称` | `text` | - | Creator display name |
| 6 | `命中关键词` | `text` | - | Search/discovery hit keyword |
| 7 | `受众辐射(推断)` | `select` | `欧美为主` / `日本为主` / `巴西/葡语拉美为主` / `分散无主导` / `非欧美为主` / `未知/待核实` | Rough inference from comments/language |
| 8 | `主页URL` | `text(url)` | - | Current Step 4 canonical entry |
| 9 | `发现时间` | `datetime` | format `yyyy-MM-dd HH:mm` | Discovery timestamp |
| 10 | `业务线` | `select` | `Bloome` / `Renoise` | Missing `EdgeSpark` |
| 11 | `粗估依据` | `text` | - | Basis text shown to humans |
| 12 | `平台内ID` | `text` | - | Platform-level dedupe / fallback locator |
| 13 | `粗估得分` | `number` | precision `1` | Rough score `0-100` |
| 14 | `淘汰原因` | `text` | - | Elimination reason |
| 15 | `粉丝数` | `number` | precision `0`, thousands separator | Follower count |
| 16 | `来源记录ID` | `text` | - | Legacy logical back-reference |
| 17 | `来源` | `text` | - | Discovery source label |
| 18 | `加权ER` | `number` | precision `2` | Stored as numeric percent-style value, not Feishu percentage formatting |
| 19 | `平台` | `select` | `YouTube` / `TikTok` / `Instagram` / `Twitter` | Platform routing |
| 20 | `来源表` | `text` | - | Legacy logical back-reference |
| 21 | `对接人` | `user` | single user | Human owner for Step 4 |
| 22 | `候选状态` | `select` | `待细估` / `细估中` / `已通过` / `已淘汰` / `建联中` / `待深筛` / `已淘汰(浅筛)` | Main workflow state |

## What The Current Table Already Covers Well

- Human handoff essentials are already present:
  - `主页URL`
  - `对接人`
  - `候选状态`
  - `业务线`
- Rough screening essentials are already present:
  - `粉丝数`
  - `加权ER`
  - `近期均播放`
  - `评论质量标记`
  - `受众辐射(推断)`
  - `粗估得分`
  - `粗估依据`
- System linkage essentials are partially present:
  - `平台`
  - `平台内ID`
  - `关联主体`

## Gaps To Fix First

These are the highest-priority schema gaps relative to the current skill/process design.

### 1. Add full signal snapshot field

Recommended field:

| Field | Type | Why |
|---|---|---|
| `采集信号JSON` | long text | Let `write_candidate.py` persist the full Step 2 signal package so Step 4 can reuse it without refetching |

This is the biggest missing piece right now, because the code already supports it if the field exists.

### 2. Add signal freshness metadata

Recommended fields:

| Field | Type | Why |
|---|---|---|
| `信号采集时间` | datetime | Know when the snapshot was collected |
| `信号来源脚本` | text | e.g. `data_scrawl/youtube_data.py`, `tiktok.py`, `instagram.py`, `twitter.py` |
| `采样窗口` | text | e.g. `recent 8 videos`, `recent 12 posts`, `recent 20 tweets` |

Without this, people and agents cannot judge whether a snapshot is stale or comparable.

### 3. Add business-useful summary fields instead of dumping everything into text

Recommended fields:

| Field | Type | Why |
|---|---|---|
| `内容赛道` | multi-select or text | Quick routing by niche/topic |
| `内容摘要` | text | One-line what this creator actually posts |
| `代表作摘要` | text | Short summary of the top recent post/video/tweet |
| `商业化信号` | select | `强` / `中` / `弱` / `未知`; helps prioritize leads |

The candidate pool is a workbench, so a few readable summary fields will be more useful than forcing humans to open raw JSON every time.

### 4. Add review-operation metadata

Recommended fields:

| Field | Type | Why |
|---|---|---|
| `分配时间` | datetime | When the owner took it |
| `最后处理时间` | datetime | Last workflow touch |
| `细估完成时间` | datetime | Completion timestamp |
| `最后操作Agent` | text | Which agent/script last touched the row |

These make the candidate pool easier to manage operationally once many people are using their own agents.

## Recommended Additional Fields By Priority

## P0: Should add now

| Field | Type | Reason |
|---|---|---|
| `采集信号JSON` | long text | Required for signal reuse and consistency with current code |
| `信号采集时间` | datetime | Prevent stale-signal reuse |
| `内容摘要` | text | Makes the pool readable without reopening raw signals |
| `代表作摘要` | text | Gives humans quick context when assigning |

## P1: Strongly recommended

| Field | Type | Reason |
|---|---|---|
| `内容赛道` | multi-select | Better filtering and assignment |
| `商业化信号` | select | Useful because TikTok/YouTube comment and sponsor signals already exist |
| `评论语言Top1` | text | Handy surfaced summary from existing signal package |
| `评论语言Top2` | text | Same |
| `重复评论风险` | select | `低` / `中` / `高`; easier than reading raw numbers |
| `最近活跃时间` | datetime or text | Important for triage and freshness |

## P2: Nice to have

| Field | Type | Reason |
|---|---|---|
| `采样覆盖度` | text | e.g. `8 videos / 30 comments`, useful for confidence |
| `高购买意图评论数` | number | Especially useful for TikTok / YouTube business value |
| `信号完整度` | select | `完整` / `部分缺失` / `需重采` |
| `细估入口备注` | text | Freeform note from human to agent |

## Fields That Should Probably Be Removed Or Reworked

| Field | Suggestion | Why |
|---|---|---|
| `来源表` | Re-evaluate | Step 3 no longer writes platform detail tables, so this is less meaningful now |
| `来源记录ID` | Re-evaluate | Same as above; may be legacy from old write-first design |

## Enum / Workflow Fixes Needed

### `业务线`

Current live options:

- `Bloome`
- `Renoise`

Should be aligned to the skill/process docs:

- `Bloome`
- `Renoise`
- `EdgeSpark`

### `候选状态`

Current options are workable, but the field description is stale and mentions values not actually present, such as:

- `待初筛`
- `已封杀-印度`
- `已封杀-养号`
- `已初筛入库`

Recommendation:

- Either add those states back intentionally
- Or update the field description to match the actual workflow states only

## Suggested Minimal Candidate Pool Shape

If the goal is to keep the pool light but still useful, the recommended minimum set is:

- `账号名称`
- `平台`
- `主页URL`
- `平台内ID`
- `业务线`
- `对接人`
- `候选状态`
- `发现时间`
- `粉丝数`
- `加权ER`
- `近期均播放`
- `评论质量标记`
- `受众辐射(推断)`
- `粗估得分`
- `粗估依据`
- `内容摘要`
- `代表作摘要`
- `采集信号JSON`
- `信号采集时间`
- `关联主体`

## Suggested Next Actions

1. Remove or freeze `@handle`
1. Add `EdgeSpark` to `业务线`
2. Add `采集信号JSON`
3. Add `信号采集时间`
4. Add `内容摘要` and `代表作摘要`
5. Clean up stale description text on `候选状态`
