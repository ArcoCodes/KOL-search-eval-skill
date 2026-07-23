#!/usr/bin/env python3
"""YouTube 信号采集统一入口。

给定 YouTube 主页 URL，一次性输出 references/platform-signal-collection.csv
约定的 YouTube 信号 JSON：
- metrics: 频道基础信息、抽样视频指标、近期 Top、月度趋势、数据来源、缺失字段
- comments: 评论质量、评论语言分布、评论样本
- sponsor_intent: 商单痕迹、购买意图

它只产出"信号"，不产出"结论"。粗估/细估由 Agent 负责。

用法:
    python3 data_scrawl/youtube_data.py <youtube_homepage_url> [--n 8] [--comment-videos 4] [--per 60]
"""
import argparse
import collections
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import tikhub

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIKHUB_BASE = "https://api.tikhub.io"
TIKHUB_MIN_INTERVAL = 0.12
THROTTLE_MARKERS = ("confirm you", "not a bot", "sign in to confirm", "http error 429",
                    "too many requests", "rate limit", "captcha")
_last_tikhub_call = [0.0]

# 评论质量规则
GENERIC = [
    r"\bnice\b", r"\bgreat\b", r"\bgood\b", r"\bamazing\b", r"\bawesome\b",
    r"\binformative\b", r"\bvery\s+(helpful|nice|good|informative|powerful|interesting)\b",
    r"\bthanks?\s+(for|you)\b", r"\bthank you\b", r"\bkeep it up\b", r"\blove (your|this)\b",
    r"\bvaluable\b", r"\bhelpful\b", r"\bbest video\b", r"\bwell done\b", r"\bsuperb\b",
    r"\bexcellent\b", r"\bwonderful\b", r"\bvideo\b.*\b(nice|great|good|amazing)\b",
]
GENERIC_RE = re.compile("|".join(GENERIC), re.I)
PROMO_RE = re.compile(r"\b(giveaway|winner|enter|prize|claim|tag your|comment below)\b", re.I)
SCRIPTS = {
    "阿拉伯(中东)": r"[؀-ۿ]",
    "印地/天城(印度)": r"[ऀ-ॿ]",
    "孟加拉": r"[ঀ-৿]",
    "中日韩": r"[一-鿿]",
    "韩文": r"[가-힯]",
    "假名(日)": r"[぀-ヿ]",
    "西里尔(俄)": r"[Ѐ-ӿ]",
    "泰文": r"[฀-๿]",
}
SCRIPTS_RE = {k: re.compile(v) for k, v in SCRIPTS.items()}
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿←-⇿⬀-⯿]")
LATIN_LANG_HINTS = [
    ("葡萄牙语", re.compile(r"[ãõ]|ç[ãâa]|\b(não|você|obrigad|muito|vou|isso|cara|valeu|gente|tá|né)\b", re.I)),
    ("西班牙语", re.compile(r"[ñ¿¡]|\b(gracias|muy|hola|pero|esto|cómo|qué|para|este|gran)\b", re.I)),
    ("法语", re.compile(r"\b(merci|très|bonjour|c'est|vous|pour|cette|génial)\b|[àâçéèêëîïôûù]{2,}", re.I)),
    ("德语", re.compile(r"[äöüß]|\b(und|nicht|sehr|danke|ich|das|ist|auch|wie)\b", re.I)),
]

# 商单/购买意图规则
PROMO_CODE_RE = re.compile(r"\b(use|with)\s+code\b|\bpromo\s*code\b|\bcoupon\b|\bdiscount code\b|\bcode\s+[A-Z0-9]{3,}\b", re.I)
SPONSOR_RE = re.compile(r"\bsponsor|\bbrought to you by\b|\bsponsored\b|\bpartnered with\b|#ad\b|paid promotion", re.I)
AFFIL_RE = re.compile(r"\baffiliate\b|amzn\.to|geni\.us|bit\.ly|tidd\.ly|shorturl|linktr\.ee|/discount/|[?&]ref=|utm_", re.I)
URL_RE = re.compile(r"https?://([^/\s]+)")
INTENT_EN = (r"where (can i|to|do i) (buy|get|download|find)|\bis it free\b|\bhow much\b|\bprice\b|\bcost\b|"
             r"does it work|\bsign(ed)? up\b|\bjust (bought|got|installed|tried)\b|\bi('| wi)ll try\b|\blink (to|for|please|pls)\b")
INTENT_PT = (r"\bvou (testar|usar|experimentar|assinar|comprar|baixar)\b|\b(usei|testei|comprei|instalei|assino)\b|"
             r"\bvale a pena\b|\bquanto custa\b|\b(é|e) gr[áa]tis\b|\bqual (o|é o) link\b|\bonde (baixar|comprar)\b|\bganhou um inscrito\b")
INTENT_ES = (r"\bvoy a probar\b|\blo (prob[ée]|us[ée]|compr[ée])\b|\bcu[áa]nto cuesta\b|\bes gratis\b|\bvale la pena\b|"
             r"\bd[óo]nde (descargar|comprar)\b|\bel (enlace|link)\b|\bme suscrib")
INTENT_RE = re.compile("|".join([INTENT_EN, INTENT_PT, INTENT_ES]), re.I)
PT_HINT_RE = re.compile(r"[ãõ]|\b(não|você|muito|obrigad|maravilh|adorei|cara|gente|valeu)\b", re.I)
ES_HINT_RE = re.compile(r"[ñ¿¡]|\b(gracias|muy|hola|gratis|enlace|suscrib|bueno)\b", re.I)


def run_ytdlp(args, timeout=180):
    proc = subprocess.run(["yt-dlp", *args], capture_output=True, text=True, timeout=timeout)
    return proc.stdout, proc.returncode, proc.stderr


def _tikhub_key():
    key = os.environ.get("TIKHUB_API_KEY")
    if key:
        return key.strip()
    env_path = os.path.join(PARENT_DIR, ".env")
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
        print(f"[youtube_data] TikHub 调用失败 {path}: {exc}", file=sys.stderr, flush=True)
        return None


def is_throttled(stderr):
    text = (stderr or "").lower()
    return any(marker in text for marker in THROTTLE_MARKERS)


def base_url(raw):
    raw = raw.strip()
    return raw.rstrip("/")


def fetch_about(url):
    """从频道 /about 页读取创作者自报国家。"""
    try:
        req = urllib.request.Request(url + "/about", headers={
            "User-Agent": _UA,
            "Accept-Language": "en-US",
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8", "replace")
    except Exception:
        return None, None
    country_match = re.search(r'"country":"([^"]+)"', html)
    return country_match.group(1) if country_match else None


def fetch_root(url):
    stdout, code, _ = run_ytdlp(["--flat-playlist", "--playlist-end", "1", "-J", url], timeout=150)
    return json.loads(stdout) if code == 0 and stdout.strip() else {}


def fetch_video_ids(url, limit):
    stdout, code, stderr = run_ytdlp(["--flat-playlist", "--playlist-end", str(limit), "-J", url + "/videos"], timeout=150)
    if code != 0 or not stdout.strip():
        raise RuntimeError(f"取频道视频失败: {stderr[:300]}")
    payload = json.loads(stdout)
    return [entry["id"] for entry in (payload.get("entries") or []) if entry.get("id")]


def recent_video_ids(channel_url, limit):
    url = base_url(channel_url)
    if not url.endswith("/videos"):
        url += "/videos"
    stdout, code, stderr = run_ytdlp(["--flat-playlist", "--playlist-end", str(limit), "--print", "id", url], timeout=120)
    if code != 0:
        raise RuntimeError(stderr[:300])
    return [line for line in stdout.strip().splitlines() if line]


def count_tab(url, tab):
    stdout, _, _ = run_ytdlp(["--flat-playlist", "--playlist-end", "1000", "--print", "id", f"{url}/{tab}"], timeout=150)
    return len([line for line in stdout.strip().splitlines() if line])


def fetch_video_meta(video_id):
    stdout, code, _ = run_ytdlp(["-J", "--skip-download", f"https://www.youtube.com/watch?v={video_id}"], timeout=150)
    return json.loads(stdout) if code == 0 and stdout.strip() else None


def ytdlp_comments(video_id, per, sort="top", retries=2):
    throttled = False
    for attempt in range(retries + 1):
        stdout, code, stderr = run_ytdlp([
            "--skip-download",
            "--write-comments",
            "--extractor-args", f"youtube:max_comments={per},all,0;comment_sort={sort}",
            "-J", f"https://www.youtube.com/watch?v={video_id}",
        ], timeout=180)
        if is_throttled(stderr):
            throttled = True
            break
        if code == 0 and stdout.strip():
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = None
            if payload and payload.get("comments"):
                return payload, throttled
        if attempt < retries:
            time.sleep(4 * (attempt + 1))
    return None, throttled


def tikhub_comments(video_id, per):
    resp = _tikhub_get("/api/v1/youtube/web_v2/get_video_comments", {"video_id": video_id})
    if not resp or resp.get("code") != 200:
        return None
    raw = (resp.get("data") or {}).get("comments") or []
    out = []
    for comment in raw[:per]:
        author = comment.get("author") or {}
        like_count = str(comment.get("like_count") or "0").replace(",", "").strip()
        out.append({
            "text": comment.get("content") or "",
            "author": author.get("display_name") if isinstance(author, dict) else author,
            "like_count": int(like_count) if like_count.isdigit() else 0,
            "author_is_uploader": bool(author.get("is_uploader")) if isinstance(author, dict) else False,
        })
    return out or None


def fetch_comments(video_id, per, sort="top"):
    payload, throttled = ytdlp_comments(video_id, per, sort)
    if payload:
        payload["source"] = "yt-dlp"
        return payload
    if throttled and _tikhub_key():
        print(f"[youtube_data] yt-dlp 被限流，回退 TikHub: {video_id}", file=sys.stderr, flush=True)
        comments = tikhub_comments(video_id, per)
        if comments:
            return {
                "comments": comments,
                "source": "tikhub",
                "view_count": None,
                "like_count": None,
                "comment_count": None,
                "title": None,
            }
    return None


def detect_comment_lang(text):
    for name, regex in SCRIPTS_RE.items():
        if regex.search(text):
            return name.split("(")[0]
    for name, regex in LATIN_LANG_HINTS:
        if regex.search(text):
            return name
    return "英语/其他拉丁"


def tier_label(subs):
    if not subs:
        return "未知"
    for hi, label in [
        (1000, "<1K 纳米"),
        (10_000, "1K–10K 微型"),
        (50_000, "10K–50K 小型"),
        (500_000, "50K–500K 中型"),
        (5_000_000, "500K–5M 大型"),
    ]:
        if subs < hi:
            return label
    return "5M+ 头部"


def iso_to_yyyymmdd(text):
    if not text:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(text))
    return f"{match.group(1)}{match.group(2)}{match.group(3)}" if match else None


def analyze_metrics(channel_url, sample_videos):
    url = base_url(channel_url)
    root = fetch_root(url)
    creator_country = fetch_about(url)

    channel_id = root.get("channel_id")
    tikhub_channel = None
    if tikhub.has_key() and (not root.get("channel_follower_count") or not root.get("view_count")
                             or not creator_country or not channel_id):
        resolved_id = channel_id or tikhub.resolve_channel_id(url)
        if resolved_id:
            tikhub_channel = tikhub.channel_info(resolved_id)
            if tikhub_channel:
                channel_id = channel_id or tikhub_channel.get("channel_id")
                creator_country = creator_country or tikhub_channel.get("creator_country")
                print(
                    f"[youtube_data] TikHub 兜底频道信息: {tikhub_channel.get('name')} "
                    f"subs={tikhub_channel.get('subscriber_count')} "
                    f"views={tikhub_channel.get('total_views')} "
                    f"country={tikhub_channel.get('creator_country')}",
                    file=sys.stderr,
                    flush=True,
                )

    try:
        video_ids = fetch_video_ids(url, sample_videos)
    except RuntimeError as exc:
        if tikhub.has_key():
            resolved_id = channel_id or tikhub.resolve_channel_id(url)
            video_ids = tikhub.channel_videos(resolved_id, sample_videos) if resolved_id else []
            print(
                f"[youtube_data] yt-dlp 视频列表限流，TikHub 兜底: 拿到 {len(video_ids)} 条 ID",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"[youtube_data] 视频列表获取失败且无 TikHub key: {exc}", file=sys.stderr, flush=True)
            video_ids = []

    videos = []
    for video_id in video_ids:
        meta = fetch_video_meta(video_id)
        if meta:
            videos.append({
                "id": video_id,
                "title": meta.get("title"),
                "upload_date": meta.get("upload_date"),
                "duration_sec": meta.get("duration"),
                "view_count": meta.get("view_count"),
                "like_count": meta.get("like_count"),
                "comment_count": meta.get("comment_count"),
                "language": meta.get("language"),
                "categories": meta.get("categories") or [],
                "subtitles_langs": sorted(k for k in (meta.get("subtitles") or {}) if k != "live_chat"),
                "tags": (meta.get("tags") or [])[:15],
                "description": (meta.get("description") or "")[:600],
                "source": "yt-dlp",
            })
            continue
        if tikhub.has_key():
            video = tikhub.video_info(video_id)
            if video:
                videos.append({
                    "id": video_id,
                    "title": video.get("title"),
                    "upload_date": iso_to_yyyymmdd(video.get("publish_date")),
                    "duration_sec": video.get("duration_sec"),
                    "view_count": video.get("view_count"),
                    "like_count": video.get("like_count"),
                    "comment_count": video.get("comment_count"),
                    "language": None,
                    "categories": [],
                    "subtitles_langs": [],
                    "tags": video.get("tags") or [],
                    "description": video.get("description") or "",
                    "source": "tikhub",
                })

    viewable_videos = [video for video in videos if video.get("view_count")]
    views = [video["view_count"] for video in viewable_videos]
    total_views_recent = sum(views)
    total_likes_recent = sum(video.get("like_count") or 0 for video in viewable_videos)
    total_comments_recent = sum(video.get("comment_count") or 0 for video in viewable_videos)

    dates = sorted(datetime.strptime(video["upload_date"], "%Y%m%d") for video in videos if video.get("upload_date"))
    avg_upload_gap = round((dates[-1] - dates[0]).days / (len(dates) - 1), 1) if len(dates) >= 2 else None

    recent_top = sorted([
        {
            "title": video["title"],
            "views": video["view_count"],
            "likes": video.get("like_count"),
            "comments": video.get("comment_count"),
            "date": video.get("upload_date"),
            "url": f"https://www.youtube.com/watch?v={video['id']}",
        }
        for video in viewable_videos
    ], key=lambda item: item["views"], reverse=True)[:10]

    views_by_month = {}
    for video in viewable_videos:
        month = video["upload_date"][:6] if video.get("upload_date") else None
        if month:
            views_by_month.setdefault(month, []).append(video["view_count"])
    monthly_trend = [
        {"month": f"{month[:4]}-{month[4:]}", "videos": len(vals), "avg_views": round(statistics.mean(vals))}
        for month, vals in sorted(views_by_month.items())
    ]

    total_videos = count_tab(url, "videos")
    shorts_count = count_tab(url, "shorts")
    if not total_videos and tikhub_channel and tikhub_channel.get("video_count"):
        total_videos = tikhub_channel["video_count"]

    subscriber_count = root.get("channel_follower_count") or (tikhub_channel.get("subscriber_count") if tikhub_channel else None)
    lifetime_views = root.get("view_count") or (tikhub_channel.get("total_views") if tikhub_channel else None)
    description = root.get("description") or ""
    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", description)
    thumbnails = root.get("thumbnails") or []
    avatar = thumbnails[-1]["url"] if thumbnails else None

    category_counter = {}
    tag_counter = {}
    for video in viewable_videos:
        for category in (video.get("categories") or []):
            category_counter[category] = category_counter.get(category, 0) + 1
        for tag in video.get("tags") or []:
            tag_counter[tag] = tag_counter.get(tag, 0) + 1

    category = max(category_counter, key=category_counter.get) if category_counter else None
    raw_tags_top = [tag for tag, _ in sorted(tag_counter.items(), key=lambda item: -item[1])[:15]]
    subtitle_langs = sorted({lang for video in viewable_videos for lang in (video.get("subtitles_langs") or [])})
    subtitle_summary = "，".join(subtitle_langs) if subtitle_langs else "无人工字幕（仅自动生成）"
    latest_upload = None
    if dates:
        latest_date = max(dates)
        latest_upload = f"{latest_date.year}-{latest_date.month:02d}-{latest_date.day:02d} 00:00:00"

    video_sources = {video.get("source") for video in videos}
    return {
        "channel": {
            "name": root.get("channel") or root.get("title") or (tikhub_channel.get("name") if tikhub_channel else None),
            "channel_id": channel_id,
            "channel_url": root.get("channel_url") or root.get("webpage_url"),
            "subscriber_count": subscriber_count,
            "tier": tier_label(subscriber_count),
            "creator_country": creator_country,
            "avatar": avatar or (tikhub_channel.get("avatar") if tikhub_channel else None),
            "email": emails[0] if emails else None,
            "category": category,
            "subtitle_summary": subtitle_summary,
            "raw_tags_top": raw_tags_top,
            "latest_upload": latest_upload,
            "total_views": lifetime_views,
            "total_videos": total_videos,
            "shorts_count": shorts_count,
            "avg_views_channel": round(lifetime_views / total_videos) if lifetime_views and total_videos else None,
            "description": description[:300],
        },
        "metrics": {
            "sampled_videos": len(viewable_videos),
            "avg_views_recent": round(statistics.mean(views)) if views else None,
            "median_views_recent": round(statistics.median(views)) if views else None,
            "avg_likes_recent": round(statistics.mean([video.get("like_count") or 0 for video in viewable_videos])) if viewable_videos else None,
            "avg_comments_recent": round(statistics.mean([video.get("comment_count") or 0 for video in viewable_videos])) if viewable_videos else None,
            "engagement_rate_weighted": round((total_likes_recent + total_comments_recent) / total_views_recent, 4) if total_views_recent else None,
            "engagement_rate_simple": round(statistics.mean([
                ((video.get("like_count") or 0) + (video.get("comment_count") or 0)) / video["view_count"]
                for video in viewable_videos
            ]), 4) if viewable_videos else None,
            "like_rate_weighted": round(total_likes_recent / total_views_recent, 4) if total_views_recent else None,
            "comment_rate_weighted": round(total_comments_recent / total_views_recent, 4) if total_views_recent else None,
            "view_sub_ratio": round(statistics.median(views) / subscriber_count, 4) if views and subscriber_count else None,
            "upload_interval_days_avg": avg_upload_gap,
        },
        "recent_top": recent_top,
        "monthly_trend": monthly_trend,
        "videos": videos,
        "data_source": {
            "channel": "tikhub" if tikhub_channel else "yt-dlp",
            "videos": "mixed" if video_sources == {"yt-dlp", "tikhub"} else next(iter(video_sources), "yt-dlp"),
        },
        "missing_fields": ([] if lifetime_views else [
            "频道总观看 total_views —— yt-dlp 不提供且 TikHub 兜底也未取到；需求和全部视频或 Modash"
        ]) + [
            "受众画像(性别/年龄/国家/语言占比) —— 需 Modash 类平台或 media kit",
            "订阅增长历史曲线 —— yt-dlp 无历史；趋势仅由采样视频近似",
            "关注它的知名账号 / 相似频道 lookalikes —— 需 Modash",
            "全站历史热门 Top —— 当前仅采样窗口内 Top；全量需深抓所有视频",
            "创作者本人性别/年龄/国家 —— 一般不可得",
        ],
    }


def analyze_comments(channel_url, comment_videos, per):
    video_ids = recent_video_ids(channel_url, comment_videos)
    all_comments = []
    newest_comments = []
    per_video = []
    sources = set()

    for video_id in video_ids:
        payload = fetch_comments(video_id, per)
        if not payload:
            continue
        source = payload.get("source", "yt-dlp")
        sources.add(source)
        comments = payload.get("comments") or []
        all_comments.extend(comments)
        if source == "yt-dlp":
            time.sleep(2)
            newest = fetch_comments(video_id, per, sort="new")
            if newest:
                newest_comments.extend(newest.get("comments") or [])
            time.sleep(2)
        per_video.append({
            "id": video_id,
            "title": (payload.get("title") or "")[:60],
            "views": payload.get("view_count"),
            "likes": payload.get("like_count"),
            "comment_count": payload.get("comment_count"),
            "sampled": len(comments),
        })

    total_comments = len(all_comments)
    if total_comments == 0:
        return {"error": "no comments fetched"}

    texts = [(comment.get("text") or "") for comment in all_comments]
    authors = [comment.get("author") for comment in all_comments]
    likes = [comment.get("like_count") or 0 for comment in all_comments]
    generic_hits = sum(1 for text in texts if GENERIC_RE.search(text))
    promo_hits = sum(1 for text in texts if PROMO_RE.search(text))

    def norm(text):
        return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()

    normalized_pairs = [(norm(text), author) for text, author in zip(texts, authors) if len(norm(text)) >= 15]
    authors_by_text = collections.defaultdict(set)
    for normalized, author in normalized_pairs:
        authors_by_text[normalized].add(author)
    duplicate_clusters = {text: author_set for text, author_set in authors_by_text.items() if len(author_set) >= 2}
    duplicate_comment_count = sum(len(author_set) for author_set in duplicate_clusters.values())
    duplicate_example = max(duplicate_clusters.items(), key=lambda item: len(item[1]))[0][:90] if duplicate_clusters else None

    avg_len = round(sum(len(text) for text in texts) / total_comments, 1)
    emoji_heavy = sum(1 for text in texts if len(EMOJI_RE.findall(text)) >= 2)
    owner_replies = sum(1 for comment in all_comments if comment.get("author_is_uploader"))
    zero_likes = sum(1 for like in likes if like == 0)

    script_hits = {}
    for name, regex in SCRIPTS_RE.items():
        count = sum(1 for text in texts if regex.search(text))
        if count:
            script_hits[name] = count
    latin_only = sum(1 for text in texts if not any(regex.search(text) for regex in SCRIPTS_RE.values()))

    behavior_texts = texts + [(comment.get("text") or "") for comment in newest_comments]
    behavior_count = len(behavior_texts) or 1
    timestamp_re = re.compile(r"\b\d{1,2}:\d{2}\b")
    question_count = sum(1 for text in behavior_texts if "?" in text or "？" in text)
    emoji_count = sum(1 for text in behavior_texts if EMOJI_RE.search(text))
    timestamp_count = sum(1 for text in behavior_texts if timestamp_re.search(text))
    declarative_count = sum(
        1 for text in behavior_texts
        if "?" not in text and "？" not in text and not EMOJI_RE.search(text) and not timestamp_re.search(text)
    )
    real_behavior_rate = (question_count + emoji_count + timestamp_count) / behavior_count
    behavior_flag = (
        "🚩 建议人工细看评论(疑问/表情/时间戳近乎为零、陈述句占比极高)——软信号,须同类对照+人工确认,勿单独定性"
        if real_behavior_rate < 0.15 else "未触发(行为信号正常)"
    )

    author_counter = collections.Counter(authors)
    lang_counts = collections.Counter(detect_comment_lang(text) for text in texts if text.strip())
    lang_dist = {name: f"{count / total_comments * 100:.0f}%" for name, count in lang_counts.most_common(8)}

    return {
        "homepage_url": base_url(channel_url),
        "数据来源": "/".join(sorted(sources)) or "yt-dlp",
        "videos_sampled": len(per_video),
        "comments_sampled": total_comments,
        "per_video": per_video,
        "signals": {
            "泛泛灌水占比": f"{generic_hits / total_comments * 100:.0f}% ({generic_hits}/{total_comments})",
            "模板化重复评论占比": f"{duplicate_comment_count / total_comments * 100:.0f}% ({duplicate_comment_count}/{total_comments}, {len(duplicate_clusters)}组)",
            "重复评论样例": duplicate_example or "无",
            "召唤抽奖类": f"{promo_hits}/{total_comments}",
            "平均评论长度(字符)": avg_len,
            "多emoji评论占比": f"{emoji_heavy / total_comments * 100:.0f}%",
            "频道主回复数": owner_replies,
            "0赞评论占比": f"{zero_likes / total_comments * 100:.0f}%",
            "疑问句占比(软)": f"{question_count / behavior_count * 100:.0f}% (top+最新{behavior_count}条)",
            "含表情占比(软)": f"{emoji_count / behavior_count * 100:.0f}%",
            "含时间戳占比(软)": f"{timestamp_count / behavior_count * 100:.0f}%",
            "纯陈述句占比(软)": f"{declarative_count / behavior_count * 100:.0f}%",
            "真实观众行为提示": behavior_flag,
            "不同作者/总数": f"{len(author_counter)}/{total_comments}",
            "作者重复Top": author_counter.most_common(3),
            "非拉丁脚本命中(地域线索)": script_hits or "无（全拉丁/英文）",
            "评论语言分布(估算)": lang_dist,
            "纯拉丁文评论数": latin_only,
        },
        "sample": [
            {
                "author": comment.get("author"),
                "likes": comment.get("like_count") or 0,
                "text": (comment.get("text") or "").replace("\n", " ")[:120],
            }
            for comment in all_comments[:25]
        ],
    }


def analyze_sponsor_intent(channel_url, videos=8, comment_videos=3, per=60):
    video_ids = recent_video_ids(channel_url, videos)
    business_hits = 0
    domains = collections.Counter()
    descriptions_scanned = 0
    details = []

    for video_id in video_ids:
        stdout, code, _ = run_ytdlp([
            "--skip-download",
            "--print",
            "%(title)s\t%(description)s",
            f"https://www.youtube.com/watch?v={video_id}",
        ], timeout=180)
        if code != 0 or not stdout.strip():
            continue
        descriptions_scanned += 1
        title, _, description = stdout.partition("\t")
        tags = []
        if PROMO_CODE_RE.search(description):
            tags.append("折扣码")
        if SPONSOR_RE.search(description):
            tags.append("赞助措辞")
        if AFFIL_RE.search(description):
            tags.append("affiliate/带参链接")
        for domain in URL_RE.findall(description):
            domains[domain.lower()] += 1
        if tags:
            business_hits += 1
        details.append({"title": title[:50], "hits": tags})

    intent_hits = []
    total_comments = 0
    portuguese_comments = 0
    spanish_comments = 0
    for video_id in video_ids[:comment_videos]:
        payload = fetch_comments(video_id, per, sort="top")
        if not payload:
            continue
        for comment in (payload.get("comments") or []):
            text = (comment.get("text") or "").replace("\n", " ")
            total_comments += 1
            if PT_HINT_RE.search(text):
                portuguese_comments += 1
            elif ES_HINT_RE.search(text):
                spanish_comments += 1
            if INTENT_RE.search(text):
                intent_hits.append(text[:110])

    non_english = portuguese_comments + spanish_comments
    lang_hint = (
        f"葡语≈{portuguese_comments} 西语≈{spanish_comments} 其他/英文≈{total_comments - non_english}（共{total_comments}）"
        if total_comments else "n/a"
    )
    intent_coverage = "可靠(英/葡/西已覆盖)" if total_comments else "n/a"

    return {
        "homepage_url": base_url(channel_url),
        "商单": {
            "扫描视频数": descriptions_scanned,
            "含商单线索视频数": business_hits,
            "描述域名Top": domains.most_common(8),
            "明细": details,
            "_提示": "规则版有误判；描述无任何链接/affiliate 也是信号（未变现/无真实商单）",
        },
        "购买意图": {
            "扫描评论数": total_comments,
            "命中数": len(intent_hits),
            "占比": f"{len(intent_hits) / total_comments * 100:.0f}%" if total_comments else "n/a",
            "评论语言提示": lang_hint,
            "意图正则覆盖": intent_coverage,
            "样本": intent_hits[:12],
            "_提示": "已覆盖英/葡/西；其他语言需模型分类。规则仍会误判(如recommend)，Agent 须复核样本。",
        },
    }


def collect(homepage_url, sample_videos, comment_videos, per):
    output = {"homepage_url": homepage_url}
    try:
        output["metrics"] = analyze_metrics(homepage_url, sample_videos)
    except Exception as exc:
        output["metrics"] = {"error": str(exc)}
    try:
        output["comments"] = analyze_comments(homepage_url, comment_videos, per)
    except Exception as exc:
        output["comments"] = {"error": str(exc)}
    try:
        output["sponsor_intent"] = analyze_sponsor_intent(homepage_url, sample_videos, comment_videos, per)
    except Exception as exc:
        output["sponsor_intent"] = {"error": str(exc)}
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("homepage_url")
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--comment-videos", type=int, default=4)
    parser.add_argument("--per", type=int, default=60)
    args = parser.parse_args()
    if not args.homepage_url.startswith("http"):
        raise SystemExit("只支持 YouTube 主页URL。")
    print(json.dumps(collect(args.homepage_url, args.n, args.comment_videos, args.per), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
