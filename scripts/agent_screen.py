#!/usr/bin/env python3
"""Agent 粗筛信号提取：sig.json → 量化信号 + 上下文，供 Agent 综合判断。

提取规则表里难以仅凭单个指标判断的信号，让 Agent 在粗估阶段快速识别
"有没有硬伤"、内容是否相关、商业化风险是否明显。

用法:
    python3 agent_screen.py --signals /tmp/sig.json --business Renoise
输出:
    结构化 JSON 到 stdout，包含三层信号(强否决/中等否决/弱信号) + 上下文
"""
import argparse, json, re, statistics, sys

PLATFORM_OF = {"tiktok": "TikTok", "instagram": "Instagram", "twitter": "Twitter"}

COMPETITOR_KEYWORDS = {
    "Renoise": ["runway", "kling", "pika", "veo", "seedance", "luma", "haiper",
                "minimax", "heygen", "synthesia", "d-id", "colossyan"],
    "Bloome": ["cursor", "windsurf", "bolt", "lovable", "replit", "v0",
               "devin", "copilot", "codeium", "tabnine"],
    "EdgeSpark": [],
}

LISTICLE_PATTERNS = re.compile(
    r"\b(top\s*\d+|best\s*\d+|\d+\s*best|十大|最佳|盘点|合集|大比拼)\b", re.I)

SELF_MONETIZE_PATTERNS = re.compile(
    r"\b(patreon|ko-fi|buy\s*me\s*a\s*coffee|gumroad|teachable|udemy|skillshare|"
    r"my\s*course|enroll|join\s*my|membership|subscribe\s*for\s*more)\b", re.I)


def detect_platform(sig):
    plat_raw = sig.get("platform")
    if plat_raw in PLATFORM_OF:
        return PLATFORM_OF[plat_raw]
    return "YouTube"


def extract_youtube(sig):
    ch = sig["metrics"]["channel"]
    mt = sig["metrics"]["metrics"]
    videos = sig["metrics"].get("videos") or []
    recent_top = sig["metrics"].get("recent_top") or []
    comments = sig.get("comments") or {}
    sponsor = sig.get("sponsor_intent") or {}
    return {
        "name": ch.get("name"),
        "homepage_url": ch.get("channel_url") or sig.get("homepage_url"),
        "subscribers": ch.get("subscriber_count"),
        "category": ch.get("category"),
        "avg_views": mt.get("avg_views_recent"),
        "median_views": mt.get("median_views_recent"),
        "recent_top": recent_top,
        "videos": videos,
        "comment_signals": comments.get("signals") or {},
        "comment_language_dist": (comments.get("signals") or {}).get("评论语言分布(估算)") or {},
        "video_language": next((v.get("language") for v in videos if v.get("language")), None),
        "sponsor_intent": sponsor,
        "purchase_intent_count": (sponsor.get("购买意图") or {}).get("命中数") or 0,
        "purchase_intent_total": (sponsor.get("购买意图") or {}).get("扫描评论数") or 0,
        "owner_reply_rate": (comments.get("signals") or {}).get("频道主回复率"),
        "tags_top": ch.get("raw_tags_top") or [],
        "description_channel": ch.get("description") or "",
    }


def extract_other(sig):
    ch = sig["channel"]
    mt = sig["metrics"]
    recent_top = sig.get("recent_top") or []
    csig = sig.get("comment_signals") or {}
    return {
        "name": ch.get("name"),
        "homepage_url": ch.get("channel_url"),
        "subscribers": ch.get("followers"),
        "category": ch.get("category"),
        "avg_views": mt.get("avg_play") or mt.get("avg_views") or mt.get("avg_likes"),
        "median_views": mt.get("median_play"),
        "recent_top": recent_top,
        "videos": [],
        "comment_signals": csig,
        "comment_language_dist": csig.get("language_dist") or {},
        "video_language": None,
        "sponsor_intent": {},
        "purchase_intent_count": csig.get("purchase_intent_count") or 0,
        "purchase_intent_total": csig.get("n_comments") or 0,
        "owner_reply_rate": csig.get("owner_reply_rate"),
        "tags_top": [],
        "description_channel": ch.get("biography") or ch.get("signature") or "",
    }


# ── 强否决信号 ──────────────────────────────────────────────────────

def check_single_viral(d):
    """Top 1 视频占总播放 90%+ → 均播虚高"""
    top = d["recent_top"]
    if len(top) < 3:
        return None
    views_key = "views" if "views" in (top[0] or {}) else "play"
    plays = [t.get(views_key) or 0 for t in top]
    total = sum(plays)
    if total == 0:
        return None
    top1_share = max(plays) / total
    if top1_share >= 0.85:
        return {
            "triggered": True,
            "top1_views": max(plays),
            "total_views": total,
            "top1_share": round(top1_share, 3),
            "other_median": round(statistics.median(sorted(plays)[:-1])) if len(plays) > 1 else 0,
            "hint": f"Top1 占总播放 {top1_share:.0%}，其余中位 {round(statistics.median(sorted(plays)[:-1])):,}" if len(plays) > 1 else "",
        }
    return {"triggered": False, "top1_share": round(top1_share, 3)}


def check_sub_view_mismatch(d):
    """粉丝 vs 播放严重倒挂 → 大概率买粉"""
    subs = d["subscribers"]
    median = d["median_views"]
    if not subs or not median:
        return None
    ratio = median / subs
    if subs >= 50_000 and ratio < 0.002:
        return {
            "triggered": True,
            "subscribers": subs,
            "median_views": median,
            "ratio": round(ratio, 5),
            "hint": f"{subs:,} 粉但中位播放仅 {median:,}（{ratio:.2%}），大概率买粉",
        }
    if subs >= 10_000 and ratio < 0.005:
        return {
            "triggered": True,
            "subscribers": subs,
            "median_views": median,
            "ratio": round(ratio, 5),
            "hint": f"{subs:,} 粉但中位播放仅 {median:,}（{ratio:.2%}），粉播倒挂",
        }
    return {"triggered": False, "ratio": round(ratio, 5)}


def check_comment_language_mismatch(d):
    """评论语言和内容语言不一致 → 受众非表面群体"""
    vl = d["video_language"]
    cl = d["comment_language_dist"]
    if not cl or not isinstance(cl, dict):
        return None
    parsed = {}
    for lang, pct_str in cl.items():
        m = re.match(r"(\d+(?:\.\d+)?)", str(pct_str))
        if m:
            parsed[lang.lower()] = float(m.group(1))
    if not parsed:
        return None
    top_lang = max(parsed, key=parsed.get)
    top_pct = parsed[top_lang]

    en_like = sum(v for k, v in parsed.items()
                  if any(p in k for p in ["en", "english", "英", "latin", "拉丁"]))
    if vl and vl.startswith("en") and en_like < 30:
        return {
            "triggered": True,
            "video_language": vl,
            "comment_top_language": top_lang,
            "comment_top_pct": top_pct,
            "english_pct": round(en_like, 1),
            "full_dist": cl,
            "hint": f"英文内容但英语评论仅 {en_like:.0f}%，评论以 {top_lang}({top_pct:.0f}%) 为主",
        }
    return {"triggered": False, "video_language": vl, "comment_top_language": top_lang}


def check_content_relevance(d, business):
    """内容完全不相关 — 提取上下文供 Agent 判断"""
    titles = []
    for v in d["videos"][:8]:
        titles.append(v.get("title") or "")
    if not titles:
        for t in d["recent_top"][:8]:
            titles.append(t.get("title") or t.get("desc") or t.get("text") or "")

    return {
        "needs_agent": True,
        "category": d["category"],
        "video_titles": titles,
        "tags": d["tags_top"][:10],
        "channel_description": d["description_channel"][:200],
        "business": business,
    }


# ── 中等否决信号 ────────────────────────────────────────────────────

def check_competitor_binding(d, business):
    """竞品深度绑定 — 提取上下文供 Agent 判断"""
    keywords = COMPETITOR_KEYWORDS.get(business) or []
    if not keywords:
        return {"needs_agent": True, "competitor_keywords": [], "sponsor_data": d["sponsor_intent"]}
    hits = []
    sponsor = d["sponsor_intent"]
    if sponsor:
        biz_detail = (sponsor.get("商单") or {}).get("明细") or []
        for item in biz_detail:
            title = (item.get("title") or "").lower()
            for kw in keywords:
                if kw in title:
                    hits.append({"title": item.get("title"), "keyword": kw})
    for v in d["videos"][:8]:
        title = (v.get("title") or "").lower()
        desc = (v.get("description") or "").lower()
        for kw in keywords:
            if kw in title or kw in desc:
                hits.append({"title": v.get("title"), "keyword": kw})
    seen = set()
    unique_hits = []
    for h in hits:
        k = (h["title"], h["keyword"])
        if k not in seen:
            seen.add(k)
            unique_hits.append(h)
    return {
        "needs_agent": True,
        "triggered": len(unique_hits) >= 2,
        "competitor_mentions": unique_hits,
        "sponsor_data": d["sponsor_intent"],
    }


def check_content_format(d, business):
    """内容形式不适合植入 — 检测罗列型 + 无 workflow/demo"""
    titles = [v.get("title") or "" for v in d["videos"][:8]]
    if not titles:
        titles = [t.get("title") or t.get("desc") or t.get("text") or "" for t in d["recent_top"][:8]]
    listicle_count = sum(1 for t in titles if LISTICLE_PATTERNS.search(t))
    return {
        "needs_agent": True,
        "listicle_count": listicle_count,
        "total_titles": len(titles),
        "listicle_ratio": round(listicle_count / len(titles), 2) if titles else 0,
        "titles": titles,
        "hint": f"{listicle_count}/{len(titles)} 视频为罗列盘点型" if listicle_count else "",
    }


def check_purchase_intent(d):
    """评论购买意图极低"""
    total = d["purchase_intent_total"]
    hits = d["purchase_intent_count"]
    if not total or total < 10:
        return None
    ratio = hits / total
    return {
        "triggered": ratio < 0.01,
        "intent_count": hits,
        "total_comments": total,
        "ratio": round(ratio, 4),
        "hint": f"购买意图 {ratio:.1%}（{hits}/{total}）" + ("，受众看热闹不买单" if ratio < 0.01 else ""),
    }


def check_owner_interaction(d):
    """频道主零互动"""
    rate = d["owner_reply_rate"]
    if rate is None:
        return None
    if isinstance(rate, str):
        m = re.match(r"(\d+(?:\.\d+)?)", str(rate))
        rate = float(m.group(1)) / 100 if m else None
    if rate is None:
        return None
    return {
        "triggered": rate == 0,
        "owner_reply_rate": rate,
        "hint": "频道主从不回复评论，社区感弱" if rate == 0 else f"回复率 {rate:.1%}",
    }


# ── 弱信号 ──────────────────────────────────────────────────────────

def check_short_only(d):
    """全是短视频 → 无法做产品深度演示"""
    durations = [v.get("duration_sec") for v in d["videos"] if v.get("duration_sec")]
    if not durations:
        return None
    short_count = sum(1 for d in durations if d < 60)
    return {
        "triggered": short_count == len(durations) and len(durations) >= 3,
        "short_count": short_count,
        "total": len(durations),
        "avg_duration": round(statistics.mean(durations)),
        "hint": f"全部 {len(durations)} 条视频 < 60s（均长 {round(statistics.mean(durations))}s）" if short_count == len(durations) else "",
    }


def check_self_monetization(d):
    """自有变现渠道强势 — 提取上下文供 Agent 判断"""
    indicators = []
    for v in d["videos"][:8]:
        desc = (v.get("description") or "")
        matches = SELF_MONETIZE_PATTERNS.findall(desc.lower())
        if matches:
            indicators.extend(matches)
    channel_desc = d["description_channel"]
    ch_matches = SELF_MONETIZE_PATTERNS.findall(channel_desc.lower())
    if ch_matches:
        indicators.extend(ch_matches)
    sponsor = d["sponsor_intent"]
    domains = (sponsor.get("商单") or {}).get("描述域名Top") or []
    return {
        "needs_agent": True,
        "indicators": list(set(indicators)),
        "domain_top": domains[:5],
        "hint": f"发现自有变现: {', '.join(set(indicators))}" if indicators else "",
    }


def check_declining_activity(d):
    """更新趋势下行"""
    dates = []
    for v in d["videos"]:
        ud = v.get("upload_date") or v.get("date")
        if ud and len(str(ud)) >= 8:
            dates.append(str(ud)[:8].replace("-", ""))
    if not dates:
        for t in d["recent_top"]:
            ud = t.get("date")
            if ud and len(str(ud)) >= 8:
                dates.append(str(ud)[:8].replace("-", ""))
    if len(dates) < 3:
        return None
    dates_sorted = sorted(dates)
    from datetime import datetime
    try:
        dt = [datetime.strptime(d, "%Y%m%d") for d in dates_sorted]
    except ValueError:
        return None
    intervals = [(dt[i+1] - dt[i]).days for i in range(len(dt)-1)]
    if not intervals or len(intervals) < 2:
        return None
    first_half = intervals[:len(intervals)//2]
    second_half = intervals[len(intervals)//2:]
    avg_first = statistics.mean(first_half) if first_half else 0
    avg_second = statistics.mean(second_half) if second_half else 0
    declining = avg_second > avg_first * 1.8 and avg_second > 20
    return {
        "triggered": declining,
        "intervals_days": intervals,
        "avg_early": round(avg_first, 1),
        "avg_recent": round(avg_second, 1),
        "hint": f"更新间隔从 {avg_first:.0f}天 扩大到 {avg_second:.0f}天" if declining else "",
    }


# ── 主流程 ──────────────────────────────────────────────────────────

def analyze(sig, business):
    platform = detect_platform(sig)
    d = extract_youtube(sig) if platform == "YouTube" else extract_other(sig)

    signals = {
        "strong_veto": {},
        "medium_veto": {},
        "weak": {},
    }

    s = check_single_viral(d)
    if s:
        signals["strong_veto"]["播放全靠单条爆款撑"] = s

    s = check_sub_view_mismatch(d)
    if s:
        signals["strong_veto"]["粉丝vs播放严重倒挂"] = s

    s = check_comment_language_mismatch(d)
    if s:
        signals["strong_veto"]["评论语言和内容语言不一致"] = s

    signals["strong_veto"]["内容完全不相关"] = check_content_relevance(d, business)

    signals["medium_veto"]["竞品深度绑定"] = check_competitor_binding(d, business)
    signals["medium_veto"]["内容形式不适合植入"] = check_content_format(d, business)

    s = check_purchase_intent(d)
    if s:
        signals["medium_veto"]["评论购买意图极低"] = s

    s = check_owner_interaction(d)
    if s:
        signals["medium_veto"]["频道主零互动"] = s

    s = check_short_only(d)
    if s:
        signals["weak"]["无法承载深度植入"] = s

    signals["weak"]["自有变现渠道强势"] = check_self_monetization(d)

    s = check_declining_activity(d)
    if s:
        signals["weak"]["更新趋势下行"] = s

    triggered_strong = [k for k, v in signals["strong_veto"].items()
                        if v and v.get("triggered")]
    triggered_medium = [k for k, v in signals["medium_veto"].items()
                        if v and v.get("triggered")]
    triggered_weak = [k for k, v in signals["weak"].items()
                      if v and v.get("triggered")]
    needs_agent = [k for tier in signals.values()
                   for k, v in tier.items() if v and v.get("needs_agent")]

    return {
        "kol": {
            "name": d["name"],
            "homepage_url": d["homepage_url"],
            "platform": platform,
            "business": business,
            "subscribers": d["subscribers"],
            "avg_views": d["avg_views"],
            "median_views": d["median_views"],
        },
        "signals": signals,
        "summary": {
            "auto_triggered_strong": triggered_strong,
            "auto_triggered_medium": triggered_medium,
            "auto_triggered_weak": triggered_weak,
            "needs_agent_judgment": needs_agent,
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Agent 粗筛信号提取")
    ap.add_argument("--signals", required=True, help="sig.json 路径")
    ap.add_argument("--business", required=True, help="业务线: Bloome/Renoise/EdgeSpark")
    a = ap.parse_args()

    sig = json.load(open(a.signals, encoding="utf-8"))
    result = analyze(sig, a.business)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 摘要报告
    s = result["summary"]
    print("\n" + "=" * 50, file=sys.stderr)
    homepage_url = result["kol"].get("homepage_url") or ""
    print(f"Agent 粗筛: {result['kol']['name']} [{result['kol']['platform']}] {homepage_url}", file=sys.stderr)
    if s["auto_triggered_strong"]:
        print(f"⛔ 强否决触发: {', '.join(s['auto_triggered_strong'])}", file=sys.stderr)
    if s["auto_triggered_medium"]:
        print(f"⚠️  中等否决触发: {', '.join(s['auto_triggered_medium'])}", file=sys.stderr)
    if s["auto_triggered_weak"]:
        print(f"💡 弱信号触发: {', '.join(s['auto_triggered_weak'])}", file=sys.stderr)
    if s["needs_agent_judgment"]:
        print(f"🤖 需 Agent 判断: {', '.join(s['needs_agent_judgment'])}", file=sys.stderr)
    if not any([s["auto_triggered_strong"], s["auto_triggered_medium"],
                s["auto_triggered_weak"], s["needs_agent_judgment"]]):
        print("✅ 无异常信号", file=sys.stderr)
    print("=" * 50, file=sys.stderr)


if __name__ == "__main__":
    main()
