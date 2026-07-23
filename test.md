# KOL 搜索评估全流程测试记录

**需求**: 找一下youtube上higgsfield推supercomputer内容的五个KOL  
**业务线**: Renoise  
**执行时间**: 2026-07-23  

---

## Step 1: YouTube 关键词搜索

**命令**:
```bash
python3 scripts/yt_search.py "higgsfield supercomputer" --limit 50
```

**搜索策略**: yt-dlp 优先 → TikHub 兜底  
**实际使用**: TikHub（yt_dlp Python 模块未安装，yt-dlp 仅有 CLI 版本，Python API 导入失败后自动回退）

**搜索结果**:
- 总视频: 34 条
- 唯一频道: 27 个
- 新频道(待评估): 26 个
- 已有频道(跳过): 1 个 (Higgsfield AI — 官方频道，已落库)

**选取的 5 个 KOL**（按相关度和影响力人工选取）:

| # | 频道名 | Channel ID | 粉丝 | 搜索命中视频数 |
|---|--------|-----------|------|--------------|
| 1 | Roboverse | UCZ3KGRwOA_uONNE_6VGG2bA | 126K | 3 |
| 2 | AI Master | UC0yHbz4OxdQFwmVX2BBQqLg | 303K | 2 |
| 3 | Raj Photo Editing and Much More | UCqtMrF1ZSr5sPX1vgoPIefw | 3.54M | 1 |
| 4 | Jay E \| RoboNuggets | UCgscS8mBsQZ5sFRkJIFWD7Q | 157K | 1 |
| 5 | Isa does AI | UC7w-h_xk9cYZefKk-_JcKNg | 61.4K | 1 |

---

## Step 2: 信号采集 (youtube_data.py)

对 5 个频道逐个跑 `youtube_data.py`，采集频道指标、视频数据、评论信号、商单线索。

```bash
python3 scripts/data_scrawl/youtube_data.py "https://www.youtube.com/channel/{channel_id}" --n 8 --comment-videos 4
```

**采集结果汇总**:

| 频道 | 粉丝 | ER | 均播放 | 中位播放 | 国家 | 类目 | sig文件 |
|------|------|-----|--------|---------|------|------|---------|
| Roboverse | 126K | 0.03% | 18,361 | 16,866 | US | Education | /tmp/sig_roboverse.json |
| AI Master | 303K | 2.81% | 13,049 | 6,938 | US | People & Blogs | /tmp/sig_aimaster.json |
| Raj Photo Editing | 3.54M | 3.84% | 59,574 | 44,736 | India | Howto & Style | /tmp/sig_rajphoto.json |
| RoboNuggets | 157K | 2.31% | 35,771 | 28,401 | US | Education | /tmp/sig_robonuggets.json |
| Isa does AI | 61.4K | 0.04% | 11,760 | 10,602 | US | Education | /tmp/sig_isadoesai.json |

注: sig 文件因 stderr 混入需修复（去除 JSON 前的 log 行）。

---

## Step 3a: Agent 按粗估规则打分

```bash
# Agent 读取 /tmp/sig_xxx.json 和 references/rough-eval-rules.md，
# 产出 /tmp/rough_judgment_xxx.json
```

| 频道 | ER分 | 粉丝分 | 活跃分 | 评论分 | 总分 | 评论质量 | 受众辐射 | 硬分结果 |
|------|------|--------|--------|--------|------|---------|---------|---------|
| Roboverse | 0 | 15 | 20 | 30 | **65** | 真实讨论 | 欧美为主 | ✓ 通过 |
| AI Master | 20 | 15 | 20 | 30 | **85** | 真实讨论 | 欧美为主 | ✓ 通过 |
| Raj Photo Editing | 20 | 20 | 20 | 15 | **75** | 一般 | 欧美为主 | ✓ 通过 |
| RoboNuggets | 20 | 15 | 20 | 15 | **70** | 一般 | 欧美为主 | ✓ 通过 |
| Isa does AI | 0 | 15 | 20 | 15 | **50** | 一般 | 欧美为主 | ✗ 淘汰 |

**Isa does AI** 因 ER 过低(0.04%)，硬分 50 < 60 直接淘汰。

---

## Step 3b: Agent 信号提取（可选辅助）

```bash
python3 scripts/agent_screen.py --signals /tmp/sig_xxx.json --business Renoise
```

### Roboverse
- 强否决: 无触发
- 中等否决: "评论购买意图极低" 触发（0/13，但样本量极小）
- 弱信号: 无触发
- 需Agent判断: 内容相关性、竞品绑定、内容形式、自有变现

### AI Master
- 强否决: 无触发
- 中等否决: 无触发
- 弱信号: 无触发
- 需Agent判断: 内容相关性、竞品绑定、内容形式、自有变现

### Raj Photo Editing
- 强否决: 无触发
- 中等否决: "竞品深度绑定" 触发（Seedance 出现3次）
- 弱信号: 无触发
- 需Agent判断: 内容相关性、竞品绑定、内容形式、自有变现

### RoboNuggets
- 强否决: 无触发
- 中等否决: 无触发
- 弱信号: 无触发
- 需Agent判断: 内容相关性、竞品绑定、内容形式、自有变现

### Isa does AI (粗估分不达标，Agent信号仅供参考)
- 中等否决: "竞品深度绑定" 触发（veo, seedance）
- 弱信号: "自有变现" gumroad
- 备注: 已有 higgsfield affiliate 链接 (higgsfield.ai?fpr=ai&fp_sid=isa)

---

## Step 3c: Agent 综合判断

### 决策规则
- 硬分 < 60 → 直接淘汰
- 任何强否决量化触发 → 淘汰
- ≥2 个中等否决量化触发 → 淘汰
- Agent 对 needs_agent 信号逐项判断，确认内容相关性和风险

### 判断结果

#### 1. Roboverse — ✅ 通过
- **内容相关性**: 高度相关。视频全部关于 AI 视频制作（教程、电影制作、workflow），tags 含 "higgsfield"
- **竞品绑定**: 无。仅 1 条视频偶然提到 kling（FIFA 相关上下文），非深度合作
- **内容形式**: 教程+指南型，非罗列盘点，适合产品深度植入演示
- **自有变现**: 有 roboverse-ai.com 自有站，但无 Patreon/课程等强变现
- **购买意图低**: 仅 13 条评论样本，数据不可靠，不作为否决依据
- **结论**: 内容精准匹配 Renoise AI 视频赛道，教程形式天然适合产品演示

#### 2. AI Master — ✅ 通过
- **内容相关性**: 中等相关。泛 AI 工具频道，覆盖 ChatGPT/Claude/AI workflow，含 "How to Make Viral Reels with AI" 等视频相关内容
- **竞品绑定**: 无。1 次 runway 提及为新闻上下文（OpenAI 文章）
- **内容形式**: 深度教程型，平均时长 1016 秒（17 分钟），极适合产品演示
- **自有变现**: 无任何变现指标
- **结论**: 高硬分(85)，泛 AI 工具频道可自然覆盖 AI 视频工具，303K 粉丝体量好

#### 3. Raj Photo Editing — ✅ 通过（已有合作）
- **内容相关性**: 极高。视频内容全是 AI 视频制作，频道描述含 "Code: HIGGS-3OMWJ"（已有 higgsfield 推荐码）
- **竞品绑定**: Seedance 出现 3 次但属于多工具覆盖型创作者，同时推广 higgsfield。非排他绑定
- **内容形式**: 教程型，非罗列
- **自有变现**: 无
- **备注**: 已有 higgsfield affiliate，建议对接确认是否需要加深合作或已在合作体系内
- **结论**: 核心 AI 视频创作者，3.54M 大号，已有 higgsfield 合作基础

#### 4. Jay E | RoboNuggets — ❌ 淘汰（Agent 判断: 内容不相关）
- **内容相关性**: 不相关。近期全部 8 条视频均为 Claude Code / Claude Design / GPT 编程工具内容，无任何 AI 视频生成相关内容
- **淘汰原因**: 虽然硬分 70 通过，但内容方向为 AI 编程/设计工具，与 Renoise（AI 视频生成）业务线完全不匹配。受众画像为开发者/设计师，非视频创作者

#### 5. Isa does AI — ❌ 淘汰（硬分不达标）
- **淘汰原因**: 硬分 50 < 60（ER 0.04% 过低）
- **备注**: 内容实际高度相关（含 "7 Higgsfield Settings I Wish I Turned On Sooner"，已有 higgsfield affiliate 链接），但互动数据过差，投入产出比不合理

---

## Step 4: 写入候选池

所有完成粗估的 KOL 都写入候选池:

```bash
python3 scripts/write_candidate.py --signals /tmp/sig_xxx.json --judgment /tmp/rough_judgment_xxx.json \
  --source "discovery:higgsfield supercomputer" --keyword "higgsfield supercomputer"
```

| 频道 | 候选池记录 | 候选状态 |
|------|-----------|---------|
| Roboverse | recvq7DGgUYGL1 | 待细估 |
| AI Master | recvq7DXAdu5rN | 待细估 |
| Raj Photo Editing | recvq7EfreFwt7 | 待细估 |
| Jay E \| RoboNuggets | recvq7FTHJ1uwS | 已淘汰(浅筛) |
| Isa does AI | recvq7FTZ0l0DY | 已淘汰(浅筛) |

**淘汰原因**:
- **RoboNuggets**: Agent判断淘汰——内容完全不相关，近期8条视频全部为Claude/GPT编程工具内容，与Renoise(AI视频生成)业务线不匹配
- **Isa does AI**: 硬分淘汰——ER过低(0.04% << 2.0%)，粗估得分50/100未达60分线

---

## 后续步骤（待人工触发）

1. **细估触发**: 在飞书候选池多维表格中，对待细估记录填写"对接人"字段
2. **人工交接**: 对接人把候选池里的 `主页URL` 发给自己的 agent
3. **细估执行**: agent 运行 `check_kol_exists.py`，再生成 `/tmp/judge.json` 并执行 `write_kol.py --by <对接人email>`
4. **通知对接人**: 细估完成后通过飞书 IM 自建应用发送评估报告卡片给对接人

---

## 流程总结

```
搜索 (yt_search.py)
  ↓ 34条视频, 27频道, 去重+飞书查重 → 26 新频道
人工选取 5 个候选
  ↓
信号采集 (youtube_data.py × 5)
  ↓ 频道指标 + 视频数据 + 评论信号 + 商单线索
Agent 按 rough-eval-rules.md 粗估打分
  ↓ Isa does AI 淘汰 (50分 < 60)
Agent 信号提取 (agent_screen.py)
  ↓ 3层信号: 强否决/中等否决/弱信号
Agent 综合判断
  ↓ RoboNuggets 淘汰 (内容不相关)
写入候选池 (write_candidate.py)
  ↓ 5 个 KOL → 候选池（3 个待细估，2 个已淘汰浅筛）
等待人工触发细估
```

**最终结果**: 5 选 3（Roboverse, AI Master, Raj Photo Editing）进入候选池待细估。
