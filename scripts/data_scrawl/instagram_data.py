#!/usr/bin/env python3
"""KOL 价值评估 · Instagram 抓取（TikHub，付费——IG 无免费层）。
产出与 YouTube / TikTok 统一信号脚本平行的信号包，复用同一套 5 维判断。
ER 口径：IG 无统一 views → 用 (赞+评)/粉丝（IG 行业惯例）。
链路：search_users(找人) → profile(username→user_id+体量) → user_posts(逐帖赞评) 。
CLI: instagram.py {search|analyze} <keyword|username>
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

IG = "/api/v1/instagram"
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
        print(f"[instagram_data] TikHub 调用失败 {path}: {exc}", file=sys.stderr, flush=True)
        return None


def _g(path, params):
    r = _tikhub_get(path, params)
    return r.get("data", r) if isinstance(r, dict) else r


def has_key():
    return bool(_tikhub_key())


def _count(v):
    return v.get("count") if isinstance(v, dict) else v


def search_users(keyword, limit=15):
    d = _g(f"{IG}/v2/search_users", {"keyword": keyword}) or {}
    inner = d.get("data") if isinstance(d, dict) and "data" in d else d
    items = inner.get("items") if isinstance(inner, dict) else (inner if isinstance(inner, list) else [])
    out = []
    for u in (items or [])[:limit]:
        out.append({"username": u.get("username"), "user_id": str(u.get("id") or u.get("pk") or ""),
                    "name": u.get("full_name"), "verified": bool(u.get("is_verified")), "followers": None})
    return out


def profile(username):
    d = _g(f"{IG}/v1/fetch_user_info_by_username", {"username": username}) or {}
    u = (d.get("data") or {}).get("user") if isinstance(d.get("data"), dict) else d.get("user")
    u = u or {}
    if not u:
        return None
    return {
        "name": u.get("full_name"), "username": username, "user_id": str(u.get("id") or u.get("pk") or ""),
        "followers": _count(u.get("edge_followed_by")), "following": _count(u.get("edge_follow")),
        "post_count": _count(u.get("edge_owner_to_timeline_media")),
        "verified": bool(u.get("is_verified")), "is_business": bool(u.get("is_business_account")),
        "category": u.get("category_name"), "biography": u.get("biography"),
        "external_url": u.get("external_url"),
        "avatar": u.get("profile_pic_url_hd") or u.get("profile_pic_url"),
    }


def user_posts(user_id, n=12):
    d = _g(f"{IG}/v1/fetch_user_posts", {"user_id": str(user_id), "count": str(n)}) or {}
    items = d.get("items") or (d.get("data") or {}).get("items") if isinstance(d.get("data"), dict) else d.get("items")
    items = items or (d if isinstance(d, list) else [])
    out = []
    for it in (items or [])[:n]:
        cap = it.get("caption")
        out.append({"code": it.get("code") or it.get("shortcode"),
                    "desc": (cap.get("text") if isinstance(cap, dict) else cap) or "",
                    "like": it.get("like_count"), "comment": it.get("comment_count"),
                    "play": it.get("play_count"), "media_type": it.get("media_type"),
                    "taken_at": it.get("taken_at")})
    return out


def analyze(handle, n=12):
    handle = handle.lstrip("@")
    pf = profile(handle)
    if not pf:
        raise SystemExit(f"取不到 Instagram 主页: {handle}")
    posts = user_posts(pf["user_id"], n) if pf.get("user_id") else []
    pv = [p for p in posts if p.get("like") is not None]
    likes = [p["like"] or 0 for p in pv]
    comments = [p.get("comment") or 0 for p in pv]
    eng = [(p.get("like") or 0) + (p.get("comment") or 0) for p in pv]
    fol = pf.get("followers") or 0
    recent_top = sorted(
        [{"desc": p["desc"][:60], "like": p.get("like"), "comment": p.get("comment"), "play": p.get("play"),
          "url": f"https://www.instagram.com/p/{p['code']}/" if p.get("code") else None} for p in pv],
        key=lambda x: x.get("like") or 0, reverse=True)[:8]
    return {
        "platform": "instagram",
        "channel": {
            "name": pf["name"], "unique_id": pf["username"], "user_id": pf["user_id"],
            "channel_url": f"https://www.instagram.com/{pf['username']}/",
            "followers": pf["followers"], "following": pf.get("following"), "post_count": pf.get("post_count"),
            "verified": pf["verified"], "is_business": pf.get("is_business"), "category": pf.get("category"),
            "biography": pf.get("biography"), "external_url": pf.get("external_url"), "avatar": pf.get("avatar"),
        },
        "metrics": {
            "sampled_posts": len(pv),
            "avg_likes": round(statistics.mean(likes)) if likes else None,
            "avg_comments": round(statistics.mean(comments)) if comments else None,
            # IG ER = 平均(赞+评)/粉丝
            "engagement_rate_weighted": round(statistics.mean(eng) / fol, 4) if eng and fol else None,
        },
        "recent_top": recent_top,
        "comment_signals": {},
        "missing_fields": [
            "受众画像(性别/年龄/国家) —— 需 IG 后台/媒体kit",
            "内容承载 —— IG 无字幕接口；靠 caption + Gemini 看图/视频",
            "views —— 图文帖无 view 数；ER 用 (赞+评)/粉丝 口径",
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "analyze"])
    ap.add_argument("arg")
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()
    if not has_key():
        print("未配置 TIKHUB_API_KEY（IG 无免费层）。", file=sys.stderr); sys.exit(1)
    print(json.dumps(search_users(a.arg) if a.cmd == "search" else analyze(a.arg, a.n), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
