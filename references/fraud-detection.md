# YouTube KOL 刷量鉴定方法(客观指标,可用 yt-dlp 复现)

> 目的:不依赖转化数据、不靠人工读评论,仅用公开的"播放/点赞/评论"三个数,客观判断一个 YouTube 频道是否存在刷量(买播放、买赞、刷评论)。
> 起因:Shark Numbers(@IvanKv,184 万粉)合作后实际获客仅 200 多,复盘用此方法验证,六项指标全部命中异常。

---

## 一、核心原理(一句话)

**播放量和点赞可以批量购买,有内容的真实评论买不动。**

所以:
- **真实频道**:赞、评、播三者由"真人参与"同一个来源驱动,会按相对稳定的比例一起变动。
- **刷量频道**:播放和点赞被一起抬高,但评论跟不上 → 三者之间的比例关系会"裂开"。

我们要做的就是**量化这个裂缝**。

---

## 二、需要的数据(yt-dlp 全部可抓)

每条视频只需三个整数 + 可选评论时间:

| 指标 | yt-dlp 字段 | 说明 |
|---|---|---|
| 播放量 | `view_count` | 必有 |
| 点赞数 | `like_count` | 必有 |
| 评论数 | `comment_count` | 必有 |
| (可选)评论时间 | `timestamp`(配 `--write-comments`) | 用于辅助信号 C |

抓取命令示例:
```bash
# 1. 取频道视频列表(只要 id,不下载)
yt-dlp --flat-playlist -J "https://www.youtube.com/@<频道>/videos" > list.json

# 2. 逐条取元数据(取 15~20 条即可,混合热门+近期)
yt-dlp -J --skip-download "https://www.youtube.com/watch?v=<id>" \
  | jq '{id, view_count, like_count, comment_count}'

# 3.(可选)取评论及其时间戳,做辅助信号 C
yt-dlp --write-comments --skip-download "https://www.youtube.com/watch?v=<id>"
# 评论在 .info.json 的 comments[].timestamp(unix 秒)
```
> 与 Modash 的区别:Modash 的 `video-info` 返回同样的 views/likes/comments,但评论时间只有 "7 months ago" 这种相对字符串;**yt-dlp 能拿到精确 unix 时间戳,辅助信号 C 反而更准。** 所以这套方法用 yt-dlp 完全可复用,且更好。

---

## 三、指标与阈值

### A 组 —— 跨视频相关性(取同一频道 15~20 条视频计算)

逐条算出 `点赞率=赞/播放`、`评论率=评论/播放`,再算三个相关系数:

| 指标 | 健康号 | 刷量号(异常) | Shark 实测 |
|---|---|---|---|
| **corr(点赞数, 评论数)** | 0.7 ~ 0.9 | 接近 0 | **0.18** 🚩 |
| **corr(播放量, 评论率)** | ≈0 或微正 | 明显负(< −0.4) | **−0.64** 🚩 |
| **corr(播放量, 点赞率)** | ≈0 或微负 | 明显正(> +0.4) | **+0.48** 🚩 |

**逻辑**:
- 真人多 → 赞和评一起涨,所以赞评高度相关;刷量让赞独立于评变动 → 相关性塌到 0。
- 视频触达越广,掺入的路人越多,赞率/评率应走平或下降;刷量号反而"播放越高点赞率越高、评论率越低"——因为播放和赞一起买,评论买不动。

### B 组 —— 单视频比率水平(可对单条视频判断)

| 指标 | 正常区间 | 异常 | Shark 头部视频 |
|---|---|---|---|
| **点赞率 = 赞 / 播放** | 2% ~ 4% | > 8% | **10% ~ 12%** 🚩 |
| **评论/赞 = 评论数 / 赞** | 1% ~ 3% | < 0.5% | **0.05% ~ 0.5%** 🚩 |
| **评论率 = 评论 / 播放** | 视频量级而定 | 高播放却极低 | 百万播放视频 **0.05%** 🚩 |

**逻辑**:点赞率有天然上限,>8% 基本是刷;评论/赞比反映"点赞的人里有多少真在讨论",低于 0.5% 说明那些赞是空的。

### C 组 —— 辅助信号(定性旁证,不单独定罪)

- **评论时间分布**:百万播放的视频却几个月没有新评论 = 那些"播放"不是持续来访的真人。
  - 对照:健康视频每隔几分钟/小时就有新评论。
  - 用 yt-dlp 的 `comments[].timestamp` 算"最新评论距今时长"和"评论时间是否只集中在上线那一周"。

### ⚠️ 不要用的指标(实测无效/主观)
- **评论者订阅数少 ≠ 机器人**:YouTube 绝大多数真实观众根本没有自己的频道,小号是常态。实测刷量视频和正常视频的评论者都是小号,无法区分。
- **"评论读起来像广告腔"**:主观,不能作为客观证据。

---

## 四、判定规则

对一个频道取 15~20 条视频(热门 + 近期混合),跑完 A 组 3 个相关性 + B 组 3 个比率:
- **多数命中异常区间 → 客观判定刷量**,无需转化数据或人工读评论。
- Shark Numbers:**A 组 3 项 + B 组 3 项 = 六项全中**。

### 分组对比(Shark 实测,最直观)
| | 视频数 | 平均点赞率 | 平均评论率 | 评论/赞 |
|---|---|---|---|---|
| 播放 >100万 | 11 | **9.5%** | **0.053%** | **0.51%** |
| 播放 <100万 | 9 | 4.6% | 0.106% | 2.28% |

百万播放视频点赞率是低播放的 2 倍,但评论率只有一半、评论/赞比仅 1/4 —— 播放和赞一起被刷,评论留在真实水平。

> **额外结论**:Shark 被刷的是**非赞助的"爆款内容"**(刷成百万播放抬高报价),而真实赞助视频(Anker/Eufy 等)反而是几十万播放、2~6% 点赞率的真实水平。买家(我们)按"百万播放大号"付费,实际触达只有真实视频那个量级 → 解释了 200 获客。

---

## 五、参考计算脚本(Python,输入 video-info 列表)

```python
import json, glob, statistics as st

rows = []
for f in glob.glob("videos/*.json"):       # 每个文件一条视频的 {view_count,like_count,comment_count}
    v = json.load(open(f))
    if v.get("view_count"):
        rows.append({
            "views": v["view_count"],
            "likes": v.get("like_count", 0),
            "comments": v.get("comment_count", 0),
        })
for r in rows:
    r["like_rate"] = r["likes"] / r["views"]
    r["cmt_rate"]  = r["comments"] / r["views"]

def corr(xs, ys):
    n = len(xs); mx = sum(xs)/n; my = sum(ys)/n
    c  = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    sx = sum((x-mx)**2 for x in xs) ** 0.5
    sy = sum((y-my)**2 for y in ys) ** 0.5
    return c / (sx*sy) if sx*sy else 0

v  = [r["views"] for r in rows]
print("corr(likes,comments) =", round(corr([r["likes"] for r in rows],
                                            [r["comments"] for r in rows]), 2))   # 期望 0.7~0.9
print("corr(views,cmt_rate) =", round(corr(v, [r["cmt_rate"]  for r in rows]), 2))  # 期望 ≈0,异常为负
print("corr(views,like_rate)=", round(corr(v, [r["like_rate"] for r in rows]), 2))  # 期望 ≈0,异常为正
print("median like_rate     =", round(st.median(r["like_rate"] for r in rows)*100, 1), "%")  # >8% 异常
```

---

## 六、给 yt-dlp 复用的要点
1. **数据完全够用**:`view_count / like_count / comment_count` 是 yt-dlp 默认字段,不需要登录或额外权限。
2. **评论时间戳更优**:`--write-comments` 拿到的是精确 unix 时间,辅助信号 C 比 Modash 还准。
3. **样本**:每个号取 15~20 条(务必混合"全部时段热门"+"最近上传"),否则相关性不稳。
4. **阈值是经验值**:上面的区间基于 YouTube 常态 + Shark 实测,落地时建议先拿几个已知正常号/已知刷量号校准一遍再定线。
