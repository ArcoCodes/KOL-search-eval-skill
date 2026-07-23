#!/usr/bin/env python3
"""KOL 价值评估 · Twitter/X 抓取（TikHub，付费——无免费层）。
产出与其它平台平行的信号包，复用同一套 5 维判断。
ER 口径：(赞+转+回+引)/views —— Twitter 逐推有 views，用 views 口径（最准）。
链路：search(找人) → profile(screen_name→体量) → user_post_tweet(逐推 stats)。
CLI: twitter.py {search|analyze} <keyword|screen_name>
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

TW = "/api/v1/twitter/web"
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
        print(f"[twitter_data] TikHub 调用失败 {path}: {exc}", file=sys.stderr, flush=True)
        return None


def _g(path, params):
    r = _tikhub_get(path, params)
    return r.get("data", r) if isinstance(r, dict) else r


def has_key():
    return bool(_tikhub_key())


def _num(v):
    """Twitter 计数常为字符串/带逗号 → int。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(",", "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def search_users(keyword, limit=15):
    """fetch_search_timeline(People)；拿不到独立用户列表则从推文作者去重。"""
    d = _g(f"{TW}/fetch_search_timeline", {"keyword": keyword, "search_type": "People"}) or {}
    users = d.get("users") or d.get("people") or []
    out, seen = [], set()
    for u in users[:limit]:
        sn = u.get("screen_name") or u.get("profile")
        if sn and sn not in seen:
            seen.add(sn)
            out.append({"screen_name": sn, "rest_id": str(u.get("rest_id") or ""),
                        "name": u.get("name"), "followers": u.get("sub_count") or u.get("followers"),
                        "verified": bool(u.get("blue_verified"))})
    if out:
        return out
    # 回退：从 timeline 推文作者去重
    for t in (d.get("timeline") or [])[:40]:
        au = t.get("author") or {}
        sn = au.get("screen_name") or au.get("profile")
        if sn and sn not in seen:
            seen.add(sn)
            out.append({"screen_name": sn, "rest_id": str(au.get("rest_id") or ""),
                        "name": au.get("name"), "followers": au.get("sub_count") or au.get("followers"),
                        "verified": bool(au.get("blue_verified"))})
    return out[:limit]


def profile(screen_name):
    d = _g(f"{TW}/fetch_user_profile", {"screen_name": screen_name}) or {}
    if not (d.get("rest_id") or d.get("name")):
        return None
    return {
        "name": d.get("name"), "screen_name": d.get("profile") or screen_name, "rest_id": str(d.get("rest_id") or ""),
        "followers": _num(d.get("sub_count")), "following": _num(d.get("friends")),
        "blue_verified": bool(d.get("blue_verified")), "verification_type": d.get("verification_type"),
        "location": d.get("location"), "website": d.get("website"), "biography": d.get("desc"),
        "avatar": d.get("avatar"),
    }


def tweets(screen_name, n=20):
    # TikHub fetch_user_post_tweet 对混合大小写 screen_name 返回 400，需强制小写
    d = _g(f"{TW}/fetch_user_post_tweet", {"screen_name": screen_name.lower()}) or {}
    out = []
    for t in (d.get("timeline") or [])[:n]:
        out.append({"tweet_id": t.get("tweet_id"), "text": (t.get("text") or "")[:200], "lang": t.get("lang"),
                    "fav": _num(t.get("favorites")), "rt": _num(t.get("retweets")), "reply": _num(t.get("replies")),
                    "quote": _num(t.get("quotes")), "views": _num(t.get("views")), "bookmarks": _num(t.get("bookmarks")),
                    "created_at": t.get("created_at")})
    return out


def analyze(handle, n=20):
    handle = handle.lstrip("@")
    pf = profile(handle)
    if not pf:
        raise SystemExit(f"取不到 Twitter 主页: {handle}")
    tw = tweets(handle, n)
    tv = [t for t in tw if t.get("views")]
    views = [t["views"] for t in tv]
    tV = sum(views)
    tF = sum(t.get("fav") or 0 for t in tv)
    tR = sum(t.get("rt") or 0 for t in tv)
    tRe = sum(t.get("reply") or 0 for t in tv)
    tQ = sum(t.get("quote") or 0 for t in tv)
    tB = sum(t.get("bookmarks") or 0 for t in tv)
    recent_top = sorted(
        [{"text": t["text"][:60], "views": t["views"], "fav": t.get("fav"), "rt": t.get("rt"),
          "url": f"https://x.com/{handle}/status/{t['tweet_id']}" if t.get("tweet_id") else None} for t in tv],
        key=lambda x: x["views"], reverse=True)[:8]
    langs = {}
    for t in tw:
        langs[t.get("lang") or "?"] = langs.get(t.get("lang") or "?", 0) + 1
    return {
        "platform": "twitter",
        "channel": {
            "name": pf["name"], "unique_id": pf["screen_name"], "rest_id": pf["rest_id"],
            "channel_url": f"https://x.com/{pf['screen_name']}",
            "followers": pf["followers"], "following": pf.get("following"),
            "blue_verified": pf["blue_verified"], "verification_type": pf.get("verification_type"),
            "location": pf.get("location"), "website": pf.get("website"),
            "biography": pf.get("biography"), "avatar": pf.get("avatar"),
        },
        "metrics": {
            "sampled_tweets": len(tv),
            "avg_views": round(statistics.mean(views)) if views else None,
            # 加权 ER = (赞+转+回+引)/views（Twitter 曝光制，基准远低于 YT/TikTok）
            "engagement_rate_weighted": round((tF + tR + tRe + tQ) / tV, 4) if tV else None,
            "like_rate_weighted": round(tF / tV, 4) if tV else None,
            "retweet_rate_weighted": round(tR / tV, 4) if tV else None,
            "reply_rate_weighted": round(tRe / tV, 4) if tV else None,        # 回复率→真讨论
            "bookmark_rate_weighted": round(tB / tV, 4) if tV else None,      # 收藏率→强意图
        },
        "recent_top": recent_top,
        "comment_signals": {"language_dist": dict(sorted(langs.items(), key=lambda x: -x[1]))},
        "missing_fields": [
            "受众画像(性别/年龄/国家) —— 需第三方/媒体kit",
            "内容承载 —— 靠推文文本 + 链接判断",
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "analyze"])
    ap.add_argument("arg")
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    if not has_key():
        print("未配置 TIKHUB_API_KEY（Twitter 无免费层）。", file=sys.stderr); sys.exit(1)
    print(json.dumps(search_users(a.arg) if a.cmd == "search" else analyze(a.arg, a.n), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
