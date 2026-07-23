#!/usr/bin/env python3
"""TikTok 信息抓取（TikHub，付费——TikTok 无 yt-dlp 免费层，每次调用计费）。

产出与 YouTube 统一信号脚本平行的信号包，复用同一套 5 维判断 + business-standards。
链路：search_users(找人) → profile(uniqueId→secUid+体量) → user_posts(secUid→逐作品stats) → comments(反作弊+购买意图+语言)。
计数 TikTok API 多为 int，直接用。

CLI: tiktok.py {search|analyze} <keyword|tiktok_homepage_url>
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

TT = "/api/v1/tiktok/web"
TIKHUB_BASE = "https://api.tikhub.io"
TIKHUB_MIN_INTERVAL = 0.12
_last_tikhub_call = [0.0]


def _tikhub_key():
    key = os.environ.get("TIKHUB_API_KEY")
    if key:
        return key.strip()
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.strip().startswith("TIKHUB_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _tikhub_get(path, params):
    key = _tikhub_key()
    if not key:
        return None
    gap = time.monotonic() - _last_tikhub_call[0]
    if gap < TIKHUB_MIN_INTERVAL:
        time.sleep(TIKHUB_MIN_INTERVAL - gap)
    _last_tikhub_call[0] = time.monotonic()
    url = f"{TIKHUB_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": "kol-eval/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        print(f"[tiktok_data] TikHub 调用失败 {path}: {exc}", file=sys.stderr, flush=True)
        return None


def _g(path, params):
    r = _tikhub_get(f"{TT}/{path}", params)
    return r.get("data", r) if isinstance(r, dict) else r


def has_key():
    return bool(_tikhub_key())


def search_users(keyword, limit=15):
    """关键词搜 TikTok 用户（找人/发现）。"""
    d = _g("fetch_search_user", {"keyword": keyword}) or {}
    out = []
    for u in (d.get("user_list") or [])[:limit]:
        ui = u.get("user_info") or {}
        out.append({"unique_id": ui.get("unique_id"), "sec_uid": ui.get("sec_uid"),
                    "name": ui.get("nickname"), "followers": ui.get("follower_count"),
                    "verified": bool(ui.get("custom_verify") or ui.get("enterprise_verify_reason")),
                    "signature": ui.get("signature")})
    return out


def profile(unique_id):
    """主页体量。返回 sec_uid + 关键数字。"""
    d = _g("fetch_user_profile", {"uniqueId": unique_id}) or {}
    ui = d.get("userInfo") or {}
    u, st = ui.get("user") or {}, ui.get("stats") or ui.get("statsV2") or {}
    if not u:
        return None
    return {
        "name": u.get("nickname"), "unique_id": u.get("uniqueId"), "sec_uid": u.get("secUid"),
        "followers": st.get("followerCount"), "total_likes": st.get("heartCount"),
        "video_count": st.get("videoCount"), "following": st.get("followingCount"),
        "verified": bool(u.get("verified")), "signature": u.get("signature"),
        "region": u.get("region"), "avatar": u.get("avatarLarger"),
        "create_time": u.get("createTime"),
    }


def user_posts(sec_uid, n=12):
    """作品列表（含逐作品 stats）。"""
    d = _g("fetch_user_post", {"secUid": sec_uid, "count": str(n)}) or {}
    out = []
    for it in (d.get("itemList") or [])[:n]:
        st = it.get("stats") or {}
        out.append({"id": it.get("id"), "desc": (it.get("desc") or "")[:300],
                    "create_time": it.get("createTime"),
                    "play": st.get("playCount"), "digg": st.get("diggCount"),
                    "comment": st.get("commentCount"), "share": st.get("shareCount"),
                    "collect": st.get("collectCount")})
    return out


def comments(aweme_id, n=30):
    """评论（含 TikHub 原生 购买意图标记 + 逐条语言）。"""
    d = _g("fetch_post_comment", {"aweme_id": aweme_id, "count": str(n)}) or {}
    out = []
    for c in (d.get("comments") or [])[:n]:
        u = c.get("user") or {}
        out.append({"text": c.get("text") or "", "digg": c.get("digg_count"),
                    "language": c.get("comment_language"),
                    "purchase_intent": bool(c.get("is_high_purchase_intent")),
                    "author_id": u.get("uid") if isinstance(u, dict) else None,
                    "reply_count": (c.get("reply_comment_total") or
                                    len(c.get("reply_comment") or []) if c.get("reply_comment") else 0)})
    return out


def account_from_url(homepage_url):
    if not homepage_url.startswith("http"):
        raise SystemExit("analyze 只支持 TikTok 主页URL。")
    parts = [p for p in urllib.parse.urlparse(homepage_url).path.split("/") if p]
    if not parts:
        raise SystemExit("TikTok 主页URL缺少账号路径。")
    return parts[0].lstrip("@")


def analyze(homepage_url, n=12, comment_video=True):
    username = account_from_url(homepage_url)
    pf = profile(username)
    if not pf:
        raise SystemExit(f"取不到 TikTok 主页: {homepage_url}")
    posts = user_posts(pf["sec_uid"], n) if pf.get("sec_uid") else []

    pv = [p for p in posts if p.get("play")]
    plays = [p["play"] for p in pv]
    tP = sum(plays)
    tD = sum(p.get("digg") or 0 for p in pv)
    tC = sum(p.get("comment") or 0 for p in pv)
    tS = sum(p.get("share") or 0 for p in pv)

    recent_top = sorted(
        [{"desc": p["desc"][:60], "play": p["play"], "digg": p.get("digg"),
          "comment": p.get("comment"), "share": p.get("share"),
          "url": f"https://www.tiktok.com/@{username}/video/{p['id']}"} for p in pv],
        key=lambda x: x["play"], reverse=True)[:8]

    # 评论信号（取播放最高的一条视频抽样）
    csig = {}
    if comment_video and pv:
        top = max(pv, key=lambda p: p["play"])
        cs = comments(top["id"], 30)
        if cs:
            langs = {}
            for c in cs:
                langs[c["language"] or "?"] = langs.get(c["language"] or "?", 0) + 1
            texts = [c["text"].strip().lower() for c in cs if c["text"].strip()]
            dup = len(texts) - len(set(texts))
            csig = {
                "sampled_video": top["id"], "n_comments": len(cs),
                "language_dist": dict(sorted(langs.items(), key=lambda x: -x[1])),
                "purchase_intent_count": sum(1 for c in cs if c["purchase_intent"]),
                "duplicate_comments": dup,
                "samples": [{"text": c["text"][:80], "lang": c["language"],
                             "buy": c["purchase_intent"]} for c in cs[:8]],
            }

    return {
        "platform": "tiktok",
        "channel": {
            "name": pf["name"], "unique_id": pf["unique_id"], "sec_uid": pf["sec_uid"],
            "channel_url": f"https://www.tiktok.com/@{pf['unique_id']}",
            "followers": pf["followers"], "total_likes": pf["total_likes"],
            "video_count": pf["video_count"], "verified": pf["verified"],
            "region": pf.get("region"), "signature": pf.get("signature"),
            "avatar": pf.get("avatar"),
        },
        "metrics": {
            "sampled_videos": len(pv),
            "avg_play": round(statistics.mean(plays)) if plays else None,
            "median_play": round(statistics.median(plays)) if plays else None,
            # 加权 ER：(赞+评+转) / 播放（与 YouTube 口径平行）
            "engagement_rate_weighted": round((tD + tC + tS) / tP, 4) if tP else None,
            "like_rate_weighted": round(tD / tP, 4) if tP else None,
            "comment_rate_weighted": round(tC / tP, 4) if tP else None,
            "share_rate_weighted": round(tS / tP, 4) if tP else None,
            "play_follower_ratio": round(statistics.median(plays) / pf["followers"], 4)
                if plays and pf.get("followers") else None,
        },
        "recent_top": recent_top,
        "comment_signals": csig,
        "missing_fields": [
            "受众画像(性别/年龄/国家占比) —— 需 TikTok 后台/媒体kit；region 仅创作者自报",
            "内容承载 —— TikTok 无字幕接口；靠 desc + Gemini 看视频",
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "analyze"])
    ap.add_argument("arg")
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()
    if a.cmd == "analyze" and not a.arg.startswith("http"):
        raise SystemExit("analyze 只支持 TikTok 主页URL。")
    if not has_key():
        print("未配置 TIKHUB_API_KEY（TikTok 无免费层，全走 TikHub）。", file=sys.stderr); sys.exit(1)
    if a.cmd == "search":
        print(json.dumps(search_users(a.arg), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(analyze(a.arg, a.n), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
