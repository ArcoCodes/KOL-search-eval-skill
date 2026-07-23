#!/usr/bin/env python3
"""YouTube 关键词搜索 → 去重 → 查飞书已有 → 输出待评估频道列表。

用法:
    python3 yt_search.py "AI video editing" --limit 50
    python3 yt_search.py "AI video editing" --limit 50 --upload-date month
    python3 yt_search.py "AI video editing" --limit 50 --after 2026-01 --before 2026-06
    python3 yt_search.py "AI video editing" --limit 50 --collect-signals

流程:
  1. yt-dlp 优先搜索（ytsearch，免费），TikHub 兜底（按调用计费）
  2. 按 channel_id 去重，提取唯一频道
  3. 可选: --after/--before 按发布时间客户端过滤
  4. 查飞书 YouTube KOL明细表，标记已存在的频道
  5. 输出 JSON: new_channels (待评估) + existing_channels (已落库跳过)
  6. --collect-signals: 对 new_channels 逐个采信号，保存给 Agent 粗估

输出 JSON 写入 /tmp/yt_search_result.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tikhub

UPLOAD_DATE_SP = {
    "hour":  "EgIIAQ==",
    "today": "EgIIAg==",
    "week":  "EgIIAw==",
    "month": "EgIIBA==",
    "year":  "EgIIBQ==",
}


def ytdlp_search(keyword, limit=50):
    """yt-dlp ytsearch: 免费优先，返回与 TikHub 相同格式的 {channels, videos}。"""
    try:
        import yt_dlp
    except ImportError:
        print("[yt-dlp] yt_dlp 模块未安装，跳过", file=sys.stderr, flush=True)
        return None
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
    try:
        print(f"[yt-dlp] ytsearch{limit}:{keyword} ...", file=sys.stderr, flush=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(f"ytsearch{limit}:{keyword}", download=False)
        entries = result.get("entries") or [] if result else []
    except Exception as e:
        print(f"[yt-dlp] 搜索失败: {e}", file=sys.stderr, flush=True)
        return None
    if not entries:
        print("[yt-dlp] 搜索返回 0 条结果", file=sys.stderr, flush=True)
        return None
    videos = []
    channels_seen = {}
    for e in entries:
        if not e or not e.get("id"):
            continue
        cid = e.get("channel_id") or ""
        videos.append({
            "video_id": e.get("id"),
            "title": e.get("title"),
            "view_count": e.get("view_count"),
            "author": e.get("channel") or e.get("uploader"),
            "channel_id": cid,
            "url": e.get("url") or f"https://www.youtube.com/watch?v={e['id']}",
            "published_time": None,
        })
        if cid and cid not in channels_seen:
            channels_seen[cid] = {
                "channel_id": cid,
                "name": e.get("channel") or e.get("uploader"),
                "subscriber_count": e.get("channel_follower_count"),
                "url": e.get("channel_url"),
                "desc": None,
            }
    channels = list(channels_seen.values())
    print(f"[yt-dlp] 搜索完成: {len(videos)} 条视频, {len(channels)} 个频道", file=sys.stderr, flush=True)
    return {"channels": channels, "videos": videos}


def parse_published_time(text):
    """'2 weeks ago' / '3 months ago' / 'Streamed 5 days ago' → approximate datetime."""
    if not text:
        return None
    t = text.lower().replace("streamed ", "")
    m = re.match(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {
        "second": timedelta(seconds=n), "minute": timedelta(minutes=n),
        "hour": timedelta(hours=n), "day": timedelta(days=n),
        "week": timedelta(weeks=n), "month": timedelta(days=n * 30),
        "year": timedelta(days=n * 365),
    }.get(unit)
    return datetime.now() - delta if delta else None


def filter_videos_by_date(videos, after=None, before=None):
    """Client-side filter on published_time text. after/before: 'YYYY-MM' or 'YYYY-MM-DD'."""
    if not after and not before:
        return videos
    after_dt = datetime.strptime(after + "-01", "%Y-%m-%d") if after and len(after) <= 7 else (
        datetime.strptime(after, "%Y-%m-%d") if after else None)
    before_dt = datetime.strptime(before + "-28", "%Y-%m-%d") if before and len(before) <= 7 else (
        datetime.strptime(before, "%Y-%m-%d") if before else None)
    filtered = []
    for v in videos:
        dt = parse_published_time(v.get("published_time"))
        if dt is None:
            filtered.append(v)
            continue
        if after_dt and dt < after_dt:
            continue
        if before_dt and dt > before_dt:
            continue
        filtered.append(v)
    return filtered

BT = "WEcDbjFnKa48YbsKa8qc8auQnlc"
YT_TABLE = "tblzR7h4fH1y1Hkf"


def feishu_existing_channels():
    """从飞书 YouTube KOL明细表取所有已有的 主页URL（去重键）。
    返回 {channel_id: {record_id, url, name}} — channel_id 从 主页URL 末段提取。"""
    existing = {}
    offset = 0
    while True:
        r = subprocess.run(
            ["lark-cli", "base", "+record-list", "--base-token", BT, "--table-id", YT_TABLE,
             "--limit", "200", "--offset", str(offset), "--format", "json", "--as", "user"],
            capture_output=True, text=True,
        )
        try:
            d = json.loads(r.stdout).get("data", {})
        except (json.JSONDecodeError, AttributeError):
            break
        names = d.get("fields") or []
        rows = d.get("data") or []
        rids = d.get("record_id_list") or []
        url_idx = names.index("主页URL") if "主页URL" in names else None
        name_idx = names.index("账号名称") if "账号名称" in names else None
        for rid, row in zip(rids, rows):
            url = row[url_idx] if url_idx is not None and url_idx < len(row) else None
            name = row[name_idx] if name_idx is not None and name_idx < len(row) else None
            if url:
                cid = url.rstrip("/").rsplit("/", 1)[-1]
                existing[cid] = {"record_id": rid, "url": url, "name": name}
        if not d.get("has_more") or not rows:
            break
        offset += len(rows)
    return existing


def group_by_channel(videos):
    """按 channel_id 分组，每个频道保留其视频列表。"""
    channels = {}
    for v in videos:
        cid = v.get("channel_id")
        if not cid:
            continue
        if cid not in channels:
            channels[cid] = {
                "channel_id": cid,
                "author": v.get("author"),
                "videos": [],
            }
        channels[cid]["videos"].append({
            "video_id": v["video_id"],
            "title": v.get("title"),
            "view_count": v.get("view_count"),
            "url": v.get("url"),
            "published_time": v.get("published_time"),
        })
    return channels


def main():
    ap = argparse.ArgumentParser(description="YouTube 关键词搜索 + 飞书去重")
    ap.add_argument("keyword", help="搜索关键词")
    ap.add_argument("--limit", type=int, default=50, help="目标视频数量")
    ap.add_argument("--max-pages", type=int, default=10, help="最大翻页数")
    ap.add_argument("--upload-date", choices=["hour", "today", "week", "month", "year"],
                    help="YouTube 发布时间范围过滤（API 级，精确）")
    ap.add_argument("--after", help="客户端过滤：只保留此日期之后的视频，格式 YYYY-MM 或 YYYY-MM-DD")
    ap.add_argument("--before", help="客户端过滤：只保留此日期之前的视频，格式 YYYY-MM 或 YYYY-MM-DD")
    ap.add_argument("--collect-signals", action="store_true", help="自动对新频道逐个采信号，保存给 Agent 粗估")
    ap.add_argument("--auto-eval", action="store_true", help="已废弃：兼容旧入口，等同 --collect-signals，不再自动写候选池")
    ap.add_argument("--business", help="业务线标记：Bloome/EdgeSpark/Renoise")
    ap.add_argument("--eval-n", type=int, default=8, help="youtube_data.py --n 参数")
    ap.add_argument("--eval-comment-videos", type=int, default=4, help="youtube_data.py --comment-videos 参数")
    a = ap.parse_args()

    sp = UPLOAD_DATE_SP.get(a.upload_date) if a.upload_date else None
    time_desc = f"，时间范围: {a.upload_date}" if a.upload_date else ""
    if a.after or a.before:
        time_desc += f"，客户端过滤: after={a.after or '∞'} before={a.before or '∞'}"
    print(f"搜索关键词: {a.keyword}，目标: {a.limit} 条视频{time_desc}", file=sys.stderr, flush=True)

    # yt-dlp 优先搜索，TikHub 兜底
    result = ytdlp_search(a.keyword, a.limit)
    search_source = "yt-dlp"
    if not result or not result.get("videos"):
        print("[yt-dlp] 无结果，回退 TikHub ...", file=sys.stderr, flush=True)
        result = tikhub.search_all(a.keyword, limit=a.limit, max_pages=a.max_pages, sp=sp)
        search_source = "TikHub"

    videos = result["videos"]
    search_channels = result["channels"]
    print(f"搜索完成({search_source}): {len(videos)} 条视频, {len(search_channels)} 个频道", file=sys.stderr, flush=True)

    if a.after or a.before:
        before_count = len(videos)
        videos = filter_videos_by_date(videos, a.after, a.before)
        print(f"客户端时间过滤: {before_count} → {len(videos)} 条视频", file=sys.stderr, flush=True)

    by_channel = group_by_channel(videos)
    print(f"视频去重后涉及 {len(by_channel)} 个唯一频道", file=sys.stderr, flush=True)

    print("查询飞书已有记录...", file=sys.stderr, flush=True)
    existing = feishu_existing_channels()
    print(f"飞书已有 {len(existing)} 个 YouTube 频道", file=sys.stderr, flush=True)

    new_channels = []
    existing_channels = []
    for cid, info in by_channel.items():
        entry = {
            "channel_id": cid,
            "author": info["author"],
            "video_count_in_search": len(info["videos"]),
            "top_video": info["videos"][0] if info["videos"] else None,
            "videos": info["videos"],
        }
        if cid in existing:
            entry["feishu_record_id"] = existing[cid]["record_id"]
            entry["feishu_name"] = existing[cid]["name"]
            existing_channels.append(entry)
        else:
            new_channels.append(entry)

    new_channels.sort(key=lambda x: x["video_count_in_search"], reverse=True)

    output = {
        "keyword": a.keyword,
        "total_videos": len(videos),
        "unique_channels": len(by_channel),
        "new_channels": new_channels,
        "existing_channels": existing_channels,
        "search_channels_direct": search_channels,
    }

    print(f"\n=== 搜索结果摘要 ===", flush=True)
    print(f"关键词: {a.keyword}", flush=True)
    print(f"视频数: {len(videos)}", flush=True)
    print(f"唯一频道: {len(by_channel)}", flush=True)
    print(f"新频道(待评估): {len(new_channels)}", flush=True)
    print(f"已有频道(跳过): {len(existing_channels)}", flush=True)

    if existing_channels:
        print(f"\n--- 已落库频道（跳过） ---", flush=True)
        for ch in existing_channels:
            print(f"  ✓ {ch['author']} ({ch['channel_id']}) — 飞书: {ch['feishu_name']}", flush=True)

    if new_channels:
        print(f"\n--- 新频道（待评估） ---", flush=True)
        for i, ch in enumerate(new_channels, 1):
            tv = ch["top_video"]
            tv_info = f" | 热门: {tv['title'][:40]}({tv['view_count']:,} views)" if tv and tv.get("view_count") else ""
            print(f"  {i}. {ch['author']} ({ch['channel_id']}) — {ch['video_count_in_search']}条命中{tv_info}", flush=True)

    collect_signals = a.collect_signals or a.auto_eval
    if collect_signals and new_channels:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        signal_dir = f"/tmp/kol_search_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(signal_dir, exist_ok=True)
        output["signal_dir"] = signal_dir
        print(f"\n--- 采集 {len(new_channels)} 个新频道信号 ---", flush=True)
        if a.auto_eval:
            print("  ! --auto-eval 已废弃：粗估改由 Agent 按 references/rough-eval-rules.md 执行，本次仅采集信号。", flush=True)
        for i, ch in enumerate(new_channels, 1):
            cid = ch["channel_id"]
            channel_url = f"https://www.youtube.com/channel/{cid}"
            print(f"\n[{i}/{len(new_channels)}] 采集 {ch['author']} ...", file=sys.stderr, flush=True)
            r = subprocess.run(
                ["python3", os.path.join(script_dir, "data_scrawl", "youtube_data.py"), channel_url,
                 "--n", str(a.eval_n), "--comment-videos", str(a.eval_comment_videos)],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode == 0 and r.stdout.strip():
                sig_path = os.path.join(signal_dir, f"{cid}.json")
                with open(sig_path, "w", encoding="utf-8") as f:
                    f.write(r.stdout)
                ch["signal_path"] = sig_path
                ch["business"] = a.business
                print(f"  ✓ 信号已保存: {sig_path}", flush=True)
            else:
                print(f"  ✗ 信号采集失败: {r.stderr[:200]}", flush=True)

    out_path = "/tmp/yt_search_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果写入 {out_path}", file=sys.stderr, flush=True)

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
