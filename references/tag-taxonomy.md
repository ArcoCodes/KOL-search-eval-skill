# 标签体系

> 解决"原始 tags 噪声膨胀、无法聚类"的问题。**两层**：
> - **原始标签**(text)：YouTube 原始 tags 原样留存，仅供关键词检索，不聚类。
> - **受控标签**(多选)：归一映射到下方词表，用于聚类/筛选/统计。多选字段只允许出现词表内的值。
>
> 维护：本文件是词表唯一来源；新增/调整标签先改这里，再同步飞书字段选项。**业务匹配不做成标签**（在判断卡"受众匹配"维度 + 业务线标准里做）。

## 一、内容题材（每个号打 1-3 个）
| 标签 | 含义 / 典型 |
|------|-----------|
| AI视频生成 | text/image-to-video、AI 短片、视频生成工具 |
| AI图像设计 | AI 绘图、海报、设计 |
| AI头像数字人 | avatar、数字人、AI 口播形象 |
| 短视频·UGC·广告 | UGC ads、TikTok、产品视频、带货素材 |
| AI编程·开发 | Claude Code、Cursor、coding、self-host、部署 |
| AI Agent·工作流 | multi-agent、agent workflow、AI coworkers |
| 自动化·no-code | n8n、OpenClaw、automation、no-code |
| SaaS·效率工具 | SaaS builder、生产力、团队效率 |
| AI工具盘点 | "Top N AI tools" listicle（**弱意图，减分**） |
| AI新闻·模型动态 | 模型发布、行业资讯（**弱意图，减分**） |
| 创业·赚钱 | make money、AI business、副业 |

## 二、提及工具（受控，可扩展）
- **Renoise 侧**：Seedance / Runway / Kling / Veo / Pika / Midjourney / Heygen / Higgsfield / TopView / Suno / Capcut
- **Bloome 侧**：Claude Code / Cursor / n8n / OpenClaw / ChatGPT / Gemini / Copilot
- **其他常见**：Verdent / Freebuff（按需扩充；新增工具先加进本表再用）

## 三、归一规则（原始 → 受控）
1. 抓回原始 tags + 标题 + 题材 → 存「原始标签」。
2. 由 Agent（或规则+模型）映射到受控「内容题材」「提及工具」，**只输出词表内的值**；近义/版本变体合并（如 `seedance 2.0 free unlimited / seedance 2 free` → 题材`AI视频生成` + 工具`Seedance`）。
3. 写飞书多选字段前按 feishu-schema 写入要点先并入选项（不丢已有项）。
