#!/usr/bin/env python3
"""TikHub YouTube 客户端（规范化）。作为 yt-dlp 的兜底 + 补能力（发现/找人）。

策略（用户定）：yt-dlp 免费优先；被限流/拿不到时回退 TikHub（按调用计费）。
本模块只封 TikHub：内置 key 读取 + 10RPS 限流，把响应规范成统一形状
（计数从 "49.5K"/"466,521 views"/"6300位订阅者" 解析成 int）。

已用真 key 核对的接口：
  resolve_channel_id  /web/get_channel_id_v2     URL → channel_id
  channel_info        /web/get_channel_info      订阅/视频数/总播放/国家/邮箱标记/头像  ← 补 yt-dlp 拿不到的 total_views+country
  video_info          /web_v2/get_video_info     逐视频 view/like/comment/时长 → 可算 ER
  search              /web_v2/get_general_search_v2  关键词 → channels[]+videos[]  ← 发现/找人
  captions_text       /web_v2/get_video_captions_v2  字幕全文(srt→纯文本) ← "内容承载"维度的轻量信号
  comment_replies     /web_v2/get_video_comment_replies  二级评论(need_format=true)
  owner_reply_stats   (上面两个组合) 频道主回复率 ← "互动可信"反作弊信号
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

TIKHUB_BASE = "https://api.tikhub.io"
TIKHUB_MIN_INTERVAL = 0.12
_last_tikhub_call = [0.0]


def _tikhub_key():
    key = os.environ.get("TIKHUB_API_KEY")
    if key:
        return key.strip()
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
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
        print(f"[tikhub] 调用失败 {path}: {exc}", file=sys.stderr, flush=True)
        return None


def has_key():
    return bool(_tikhub_key())


def _num(s):
    """'49.5K'→49500, '466,521 views'→466521, '6300位订阅者'→6300, '1.2M'→1200000。"""
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return int(s)
    t = str(s).strip().replace(",", "")
    m = re.search(r"([\d.]+)\s*([KMB万亿])?", t, re.I)
    if not m:
        return None
    num = float(m.group(1))
    mult = {"k": 1e3, "m": 1e6, "b": 1e9, "万": 1e4, "亿": 1e8}.get((m.group(2) or "").lower(), 1)
    return int(num * mult)


def _data(resp):
    if not isinstance(resp, dict):
        return None
    if "data" in resp:
        return resp.get("data") or {}
    # 无 data 包裹时，code!=200 视为失败
    if resp.get("code") not in (None, 200):
        return None
    return resp


def _bool(v):
    return v in (True, "True", "true", 1, "1")


def resolve_channel_id(channel_url):
    d = _data(_tikhub_get("/api/v1/youtube/web/get_channel_id_v2",
                          {"channel_url": channel_url}))
    return (d or {}).get("channel_id")


def channel_videos(channel_id, n=12):
    """获取频道最近 n 条长视频的 video_id 列表（yt-dlp /videos 限流时的兜底）。"""
    d = _data(_tikhub_get("/api/v1/youtube/web/get_channel_videos_v2",
                          {"channel_id": channel_id})) or {}
    vids = d.get("videos") or []
    return [v.get("video_id") for v in vids[:n] if v.get("video_id")]


def channel_info(channel_id):
    d = _data(_tikhub_get("/api/v1/youtube/web/get_channel_info",
                          {"channel_id": channel_id}))
    if not d or not (d.get("channel_id") or d.get("title")):
        return None
    av = d.get("avatar") or []
    return {
        "name": d.get("title"),
        "channel_id": d.get("channel_id"),
        "subscriber_count": _num(d.get("subscriber_count")),
        "video_count": _num(d.get("video_count")),
        "total_views": _num(d.get("view_count")),     # yt-dlp 拿不到，这里能补
        "creator_country": d.get("country"),          # 创作者自报国家（≠受众）
        "avatar": av[-1].get("url") if av else None,
        "description": d.get("description"),
        "has_business_email": _bool(d.get("has_business_email")),
        "verified": _bool(d.get("verified")),
        "creation_date": d.get("creation_date"),
        "source": "tikhub",
    }


def video_info(video_id):
    d = _data(_tikhub_get("/api/v1/youtube/web_v2/get_video_info",
                          {"video_id": video_id}))
    if not d or not d.get("video_id"):
        return None
    return {
        "id": video_id,
        "title": d.get("title"),
        "view_count": _num(d.get("view_count")),
        "like_count": _num(d.get("like_count")),
        "comment_count": _num(d.get("comment_count")),
        "duration_sec": _num(d.get("length_seconds")),
        "channel_id": d.get("channel_id"),
        "publish_date": d.get("publish_date"),       # ISO，如 2026-06-26T11:51:54-07:00
        "description": (d.get("description") or "")[:600],
        "tags": (d.get("keywords") or [])[:15],
        "source": "tikhub",
    }


def _parse_search_page(d):
    chans = [{
        "channel_id": c.get("channel_id"), "name": c.get("title"),
        "subscriber_count": _num(c.get("subscriber_count")),
        "url": c.get("url"), "desc": c.get("description_snippet"),
    } for c in (d.get("channels") or []) if c.get("channel_id")]
    vids = [{
        "video_id": v.get("video_id"), "title": v.get("title"),
        "view_count": _num(v.get("view_count")), "author": v.get("author"),
        "channel_id": v.get("channel_id"), "url": v.get("url"),
        "published_time": v.get("published_time"),
    } for v in (d.get("videos") or []) if v.get("video_id")]
    return chans, vids, d.get("continuation_token")


def search(keyword, sp=None):
    """关键词综合搜索 → 频道 + 视频（发现/找人），单页。
    sp: YouTube search_filter, e.g. 'EgIIBQ==' for this year."""
    params = {"keyword": keyword}
    if sp:
        params["sp"] = sp
    d = _data(_tikhub_get("/api/v1/youtube/web_v2/get_general_search_v2",
                          params)) or {}
    chans, vids, token = _parse_search_page(d)
    return {"channels": chans, "videos": vids, "continuation_token": token}


def search_all(keyword, limit=50, max_pages=10, sp=None):
    """分页搜索，凑够 limit 条视频或翻完 max_pages 页。返回 {channels, videos}。
    sp: YouTube search_filter for upload date."""
    all_chans, all_vids, seen_vids = [], [], set()
    params = {"keyword": keyword}
    if sp:
        params["sp"] = sp
    d = _data(_tikhub_get("/api/v1/youtube/web_v2/get_general_search_v2",
                          params)) or {}
    chans, vids, token = _parse_search_page(d)
    for c in chans:
        if c["channel_id"] not in {x["channel_id"] for x in all_chans}:
            all_chans.append(c)
    for v in vids:
        if v["video_id"] not in seen_vids:
            seen_vids.add(v["video_id"])
            all_vids.append(v)
    page = 1
    while token and len(all_vids) < limit and page < max_pages:
        print(f"[tikhub] 搜索翻页 {page+1}，已收集 {len(all_vids)} 条视频", file=sys.stderr, flush=True)
        cont_params = {"keyword": keyword, "continuation_token": token}
        if sp:
            cont_params["sp"] = sp
        d = _data(_tikhub_get("/api/v1/youtube/web_v2/get_general_search_v2",
                              cont_params)) or {}
        chans, vids, token = _parse_search_page(d)
        if not vids and not chans:
            break
        for c in chans:
            if c["channel_id"] not in {x["channel_id"] for x in all_chans}:
                all_chans.append(c)
        for v in vids:
            if v["video_id"] not in seen_vids:
                seen_vids.add(v["video_id"])
                all_vids.append(v)
        page += 1
    return {"channels": all_chans, "videos": all_vids[:limit]}


def _strip_srt(s):
    """srt → 纯文本：去序号/时间轴行，折叠自动字幕的滚动重复。"""
    lines = []
    for ln in str(s).splitlines():
        t = ln.strip()
        if not t or t.isdigit() or "-->" in t:
            continue
        if not lines or lines[-1] != t:   # 折叠连续重复
            lines.append(t)
    return " ".join(lines)


def captions_text(video_id, language_code="en", max_chars=8000):
    """字幕全文（srt→纯文本，供"内容承载"维度判断）。无字幕/取不到返回 None，不抛。
    format 只能用 srt（'text' 会 422）。"""
    d = _data(_tikhub_get("/api/v1/youtube/web_v2/get_video_captions_v2",
                          {"video_id": video_id, "language_code": language_code, "format": "srt"}))
    content = (d or {}).get("content") if isinstance(d, dict) else None
    return _strip_srt(content)[:max_chars] if content else None


def comment_replies(continuation_token, per=30):
    """二级评论（须 need_format=true）。返回 [{text, author, is_creator, like_count}]。"""
    d = _data(_tikhub_get("/api/v1/youtube/web_v2/get_video_comment_replies",
                          {"continuation_token": continuation_token, "need_format": "true"})) or {}
    out = []
    for r in (d.get("comments") or [])[:per]:
        a = r.get("author") or {}
        out.append({"text": r.get("content") or "",
                    "author": a.get("display_name") if isinstance(a, dict) else a,
                    "is_creator": _bool(a.get("is_creator")) if isinstance(a, dict) else False,
                    "like_count": _num(r.get("like_count"))})
    return out


def owner_reply_stats(video_id, scan=10):
    """抽样回复最多的一级评论，看频道主(is_creator)是否在回复里出现 → 互动真实性信号。
    返回 {threads_checked, threads_with_owner_reply, owner_reply_rate, samples}。每线程 1 次调用。"""
    d = _data(_tikhub_get("/api/v1/youtube/web_v2/get_video_comments",
                          {"video_id": video_id})) or {}
    parents = [c for c in (d.get("comments") or [])
               if (_num(c.get("reply_count")) or 0) > 0 and c.get("reply_continuation_token")]
    parents.sort(key=lambda c: _num(c.get("reply_count")) or 0, reverse=True)
    checked = owner = 0
    samples = []
    for c in parents[:scan]:
        reps = comment_replies(c["reply_continuation_token"])
        if not reps:
            continue
        checked += 1
        ors = [r for r in reps if r["is_creator"]]
        if ors:
            owner += 1
            samples.append({"q": (c.get("content") or "")[:80], "owner_reply": (ors[0]["text"] or "")[:120]})
    return {"threads_checked": checked, "threads_with_owner_reply": owner,
            "owner_reply_rate": round(owner / checked, 2) if checked else None,
            "samples": samples[:5]}


if __name__ == "__main__":
    import json
    if len(sys.argv) < 2:
        print("用法: tikhub.py <channel|video|search|captions> <arg>"); sys.exit(1)
    cmd, arg = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    print("key:", has_key(), file=sys.stderr)
    if cmd == "channel":
        cid = arg if arg.startswith("UC") else resolve_channel_id(arg)
        print(json.dumps(channel_info(cid), ensure_ascii=False, indent=2))
    elif cmd == "video":
        print(json.dumps(video_info(arg), ensure_ascii=False, indent=2))
    elif cmd == "search":
        print(json.dumps(search(arg), ensure_ascii=False, indent=2))
    elif cmd == "captions":
        print(captions_text(arg) or "（无字幕/取不到）")
    elif cmd == "replies":  # 频道主回复率
        print(json.dumps(owner_reply_stats(arg), ensure_ascii=False, indent=2))
