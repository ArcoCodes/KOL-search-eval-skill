# 流程测试问题记录

> 测试用例: Jack Craig (https://www.youtube.com/channel/UCVljMxlPv99oN-zwLNlc7wA)
> 测试日期: 2026-07-23

---

## 已修复

### 1. write_kol.py 报告渲染 bug（3处）
- **创作者国家(自报)** 字段为空时渲染成 `None`，应显示 `—` → 已修复
- **ER 显示为小数** (0.0351) 而非百分比 (3.51%)，不直观 → 已修复，新增 `_pct()` 格式化函数
- **评论语言分布** 渲染成 Python dict 原始字符串 `{'英语/其他拉丁': '100%', ...}`，应格式化成 `英语/其他拉丁 100% / 西班牙语 0%` → 已修复

### 2. SKILL.md judge.json schema 缺失
- SKILL.md Step 4b 只列了 5 维评分 + 综合判断 + 业务线 + 报价区间 + 判断依据，但 `write_kol.py` 实际读取 20+ 个字段
- Agent 如果不看 write_kol.py 源码，无法知道需要填哪些字段，导致落库和报告大量缺项
- → 已在 SKILL.md 补全完整 judge.json schema，含所有字段、类型和枚举值

### 3. SKILL.md 粗估输出格式
- 原来是固定的 `===` 分隔框格式，在 agent 对话中渲染成 markdown 很难看
- 粗估依据示例太空泛（"85/100; 评论有具体产品问题讨论"）
- → 已改为自然语言输出，粗估依据示例已丰富

### 4. SKILL.md 细估 Report Output 格式
- 同粗估，固定格式在对话中不友好 → 已改为自然语言输出

### 5. SKILL.md 候选池 Handoff 段落冗余
- "人的操作"和"Agent 的操作"两个子节与 Detailed Eval 的 Trigger flow 高度重复 → 已精简，只保留候选池字段说明表

### 6. SKILL.md 格式小问题
- TikTok 脚本路径双反引号 → 已修复
- 候选状态枚举多余空格 → 已修复

---

## 未修复 / 待讨论

### 7. 报告"一句话"字段 fallback 不友好
- **文件**: `write_kol.py:393`
- **现象**: 报告模板读 `j.get('一句话')`，judge.json 没有此字段时 fallback 到 `判断依据[:80]`（截断），显示效果很差
- **已做**: 在 SKILL.md schema 中新增了 `一句话` 字段的说明，Agent 以后会填
- **待做**: `write_kol.py` 的 fallback 逻辑可以更智能——比如取判断依据的第一个句号前的内容，而不是硬截 80 字符

### 8. exists_in_system 路径无法测试完整细估落库
- **现象**: check_kol_exists.py 返回 `exists_in_system` 后流程终止，无法测完 write_kol.py 的飞书写入路径
- **影响**: 只能用 `--no-write` 测报告生成，无法验证飞书实际落库和通知是否正常
- **建议**: 需要一个不在系统中的新 KOL URL 才能端到端测完整流程。或者加一个 `--force` 参数允许强制细估

### 9. 信号 JSON 结构不统一
- **现象**: youtube_data.py 输出的 metrics 里有 `recent_top` 和 `monthly_trend`，但 `recent_videos` 是空列表；视频详情在顶层 `metrics.videos` 里
- **影响**: 不影响功能（write_kol.py 能正确读取），但字段分布不直观，新维护者容易困惑
- **建议**: 考虑统一信号 JSON 的结构文档（目前只有 `references/platform-signal-collection.csv`，但实际嵌套结构比 CSV 描述的复杂）

### 10. 频道评估维度需要看视频内容（Gemini）
- **现象**: `business-standards.md` 第 29 行明确写了"内容承载维度需 Gemini 看视频判断（脚本给不了）"，但整个流程没有集成 Gemini 视频分析的步骤
- **影响**: 内容承载分只能基于标题/标签/描述推断，无法判断实际视频质量和植入可行性
- **建议**: 如果 Gemini 视频分析是硬需求，应在 SKILL.md 流程中加入可选步骤；如果当前阶段不做，应在评估结论中注明"内容承载分基于元数据推断，未看实际视频"

### 11. 报告中的 ER extra_rate 未格式化
- **文件**: `write_kol.py:416-417`
- **现象**: TikTok/Twitter 的转发率/转推率如果存在，仍然渲染成小数而非百分比（因为 `_pct()` 只应用在了主 ER 行，extra_rate 的拼接在 `_pct` 定义之前）
- **影响**: 仅影响 TikTok/Twitter 平台的报告，本次 YouTube 测试未触发
- **建议**: 把 extra_rate 拼接也用 `_pct()` 格式化
