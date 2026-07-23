#!/usr/bin/env python3
"""KOL 细估落库 + 出报告（Step 4）。

输入：
  --signals  youtube_data.py 的输出 JSON（含 channel/metrics/comments/sponsor_intent）
  --judgment Agent 综合判断 JSON（Step 4 的产物，schema 见下）
动作：新建/更新平台明细(补Agent字段) → 建评估记录判断卡 → 更新候选池状态 → 生成 BLUF 报告 .md。
Step 3 只完成候选池粗估落库；本脚本负责细估阶段的正式落库。

judgment JSON schema:
{
 "业务线":"Bloome", "受众欧美辐射":"非欧美为主", "推断受众地区":"...",
 "评论质量标记":"真实讨论", "内容语言":"en", "题材_LLM":"...", "调性_LLM":"...",
 "内容题材":["AI编程·开发"], "提及工具":["Claude Code"],
 "scores":{"受众匹配":8,"内容承载":7,"流量稳定":3,"互动可信":8,"报价合理":6},
 "综合判断":"观望", "判断依据":"...", "有效播放":274,
 "合理报价区间USD":"flat/$0-150", "计价口径":"...", "状态":"未合作", "备注":"...",
 "频道评估":"...", "受众结构":"...", "流量稳定性":"...", "互动真实性":"...", "内容匹配度":"..."
}
"""
import argparse, json, subprocess, datetime, os, re, sys

BT = "WEcDbjFnKa48YbsKa8qc8auQnlc"
MAIN = "tblzR7h4fH1y1Hkf"          # YouTube KOL 明细表（原 KOL频道库）
TT = "tblsUnmLnBVfXpEg"            # TikTok KOL 明细表
IG = "tblV1DXvLLoci6ZM"            # Instagram KOL 明细表
TW = "tbltybPG07lSIuqM"            # Twitter KOL 明细表
HUB = "tblEylVlrP1Qtrmb"          # KOL总表（dashboard / 主体）
EVAL = "tblA1p25lxwHnsuV"
POOL = "tblfBV6INxVDVl6X"          # 候选池
PLATFORM_OF = {"tiktok": "TikTok", "instagram": "Instagram", "twitter": "Twitter"}
MULTI_FIELDS = {"内容题材", "提及工具"}
# 主表里的固定单选字段：给表外值飞书会整条静默写入失败，落库前必须校验。
# 选项随飞书改动需同步这里。
ENUM_FIELDS = {
    "受众欧美辐射": {"欧美为主", "日本为主", "巴西/葡语拉美为主", "分散无主导", "非欧美为主", "未知/待核实"},
    "评论质量标记": {"真实讨论", "一般", "严重灌水/疑似养号"},
    "综合判断": {"建议合作", "观望", "放弃"},
}


def validate_enums(j):
    """落库前校验单选字段值，非法直接报错（避免飞书整条静默写入失败）。"""
    errs = [f"  {k}={j.get(k)!r} 非法；合法值: {sorted(v)}"
            for k, v in ENUM_FIELDS.items() if j.get(k) and j.get(k) not in v]
    if errs:
        raise SystemExit("❌ 判断 JSON 单选字段值不合法：\n" + "\n".join(errs))


def lark(args):
    r = subprocess.run(["lark-cli", "base", *args, "--as", "user"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "raw": (r.stdout + r.stderr)[:300]}


def field_items(table):
    d = lark(["+field-list", "--base-token", BT, "--table-id", table])
    return (d.get("data") or {}).get("items") or (d.get("data") or {}).get("fields") or []


def ensure_options(table, field, values):
    """多选字段写新值前，先把新选项并入（保留原有，避免覆盖丢失）。"""
    if not values:
        return
    fid, opts = None, []
    for f in field_items(table):
        if f.get("name") == field:
            fid = f.get("id"); opts = [o.get("name") for o in (f.get("options") or [])]
    if fid is None:
        return
    new = [v for v in values if v not in opts]
    if not new:
        return
    merged = [{"name": n} for n in opts + new]
    lark(["+field-update", "--base-token", BT, "--table-id", table, "--field-id", fid,
          "--json", json.dumps({"name": field, "type": "select", "multiple": True, "options": merged}, ensure_ascii=False)])


def normalize_signals(sig):
    """把不同平台的信号归一成统一的 ch/mt（沿用 YouTube 字段名，下游不用改）。
    返回 (ch, mt, platform, homepage_url)。channel_id 统一存"平台内ID"（YT=channel_id / TikTok=sec_uid）。"""
    plat = sig.get("platform")
    if plat in ("tiktok", "instagram", "twitter"):
        c, m = sig["channel"], sig["metrics"]
        ch = {
            "name": c.get("name"),
            "channel_id": c.get("sec_uid") or c.get("user_id") or c.get("rest_id") or c.get("unique_id"),
            "channel_url": c.get("channel_url"), "avatar": c.get("avatar"),
            "subscriber_count": c.get("followers"),
            "total_videos": c.get("video_count") or c.get("post_count"),
            "creator_country": c.get("region") or c.get("location"),
            "total_likes": c.get("total_likes"),
            "tier": tier_label(c.get("followers")), "shorts_count": None, "category": c.get("category"),
            "subtitle_summary": None, "email": None, "raw_tags_top": [], "latest_upload": None,
        }
        mt = {
            "engagement_rate_weighted": m.get("engagement_rate_weighted"),
            "like_rate_weighted": m.get("like_rate_weighted"),
            "comment_rate_weighted": m.get("comment_rate_weighted"),
            "share_rate_weighted": m.get("share_rate_weighted") or m.get("retweet_rate_weighted"),
            "avg_views_recent": m.get("avg_play") or m.get("avg_views") or m.get("avg_likes"),
            "median_views_recent": m.get("median_play"),
            "view_sub_ratio": m.get("play_follower_ratio"), "upload_interval_days_avg": None,
        }
        return ch, mt, PLATFORM_OF[plat], c.get("channel_url") or ""
    # YouTube / youtube_data.py 嵌套结构
    ch, mt = sig["metrics"]["channel"], sig["metrics"]["metrics"]
    return ch, mt, "YouTube", ch.get("channel_url") or ""


def tier_label(subs):
    if not subs:
        return "未知"
    for hi, lab in [(1000, "<1K 纳米"), (10_000, "1K–10K 微型"), (50_000, "10K–50K 小型"),
                    (500_000, "50K–500K 中型"), (5_000_000, "500K–5M 大型")]:
        if subs < hi:
            return lab
    return "5M+ 头部"


def find_by_channel_id(cid):
    """按 平台内ID(channel_id 字段) 去重，返回已存在的 record_id 或 None。"""
    out = subprocess.run(["lark-cli", "base", "+record-list", "--base-token", BT, "--table-id", MAIN,
                          "--limit", "200", "--as", "user"], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if l.startswith("|") and "---" not in l]
    if not lines:
        return None
    hdr = [c.strip() for c in lines[0].split("|")[1:-1]]
    idx = {h: i for i, h in enumerate(hdr)}
    if "channel_id" not in idx or "_record_id" not in idx:
        return None
    for l in lines[1:]:
        r = [c.strip() for c in l.split("|")[1:-1]]
        if idx["channel_id"] < len(r) and r[idx["channel_id"]] == cid:
            return r[idx["_record_id"]]
    return None


def list_table(table):
    rows, ids, names, offset = [], [], [], 0
    while True:
        d = (lark(["+record-list", "--base-token", BT, "--table-id", table,
                   "--limit", "200", "--offset", str(offset), "--format", "json"]).get("data") or {})
        if not names:
            names = d.get("fields") or []
        batch = d.get("data") or []
        batch_ids = d.get("record_id_list") or []
        rows.extend(batch); ids.extend(batch_ids)
        if not d.get("has_more") or not batch:
            break
        offset += len(batch)
    return [(rid, dict(zip(names, row))) for rid, row in zip(ids, rows)]


def link_first(cell):
    return cell[0]["id"] if isinstance(cell, list) and cell and isinstance(cell[0], dict) else None


def find_in_table(table, id_field, id_value):
    """平台内按 ID 去重。返回 (record_id, fields) 或 (None, None)。"""
    if not id_value:
        return None, None
    for rid, f in list_table(table):
        if f.get(id_field) == id_value:
            return rid, f
    return None, None


def ensure_hub(name, platform, parent, existing_fields):
    """决定/创建 KOL总表主体：--parent > 已有平台记录的所属KOL > 新建。返回 hub_rid。"""
    if parent:
        return parent
    if existing_fields:
        h = link_first(existing_fields.get("所属KOL"))
        if h:
            return h
    res = lark(["+record-batch-create", "--base-token", BT, "--table-id", HUB,
                "--json", json.dumps({"fields": ["主体名称", "平台", "合作进度"],
                                      "rows": [[name or "未命名", [platform], "待联系"]]}, ensure_ascii=False)])
    return (res.get("data") or {}).get("record_id_list", [None])[0]


def hub_add_platform(hub_rid, platform):
    for rid, f in list_table(HUB):
        if rid == hub_rid:
            cur = f.get("平台") or []
            if platform not in cur:
                lark(["+record-batch-update", "--base-token", BT, "--table-id", HUB, "--json",
                      json.dumps({"record_id_list": [hub_rid], "patch": {"平台": sorted(set(cur + [platform]))}}, ensure_ascii=False)])
            return


def build_patch(sig, j, platform, today):
    """平台路由：返回 (table, patch, id_field, id_value, name, homepage_url)。"""
    if platform == "TikTok":
        c, m = sig["channel"], sig["metrics"]
        pid = c.get("sec_uid") or c.get("unique_id")
        cs = sig.get("comment_signals") or {}
        ld = cs.get("language_dist")
        patch = {
            "账号名称": c.get("name"), "sec_uid": pid,
            "主页URL": c.get("channel_url"), "头像URL": c.get("avatar"),
            "粉丝数": c.get("followers"), "总赞": c.get("total_likes"), "视频数": c.get("video_count"),
            "加权ER": m.get("engagement_rate_weighted"), "赞率": m.get("like_rate_weighted"),
            "评论率": m.get("comment_rate_weighted"), "转发率": m.get("share_rate_weighted"),
            "近期均播放": m.get("avg_play"), "中位播放": m.get("median_play"),
            "播放粉丝比": m.get("play_follower_ratio"), "创作者地区(自报)": c.get("region"),
            "签名": c.get("signature"), "内容题材": j.get("内容题材"), "提及工具": j.get("提及工具"),
            "评论语言分布": json.dumps(ld, ensure_ascii=False) if ld else None,
            "购买意图数": cs.get("purchase_intent_count"), "评论质量标记": j.get("评论质量标记"),
            "来源": j.get("来源", "kol-eval自动"), "抓取时间": today + " 00:00:00", "备注": j.get("备注", ""),
        }
        return TT, patch, "sec_uid", pid, c.get("name"), c.get("channel_url") or ""
    if platform == "Instagram":
        c, m = sig["channel"], sig["metrics"]
        pid = c.get("user_id")
        patch = {
            "账号名称": c.get("name"), "用户ID": pid,
            "主页URL": c.get("channel_url"), "头像URL": c.get("avatar"),
            "粉丝数": c.get("followers"), "关注数": c.get("following"), "帖子数": c.get("post_count"),
            "互动率": m.get("engagement_rate_weighted"), "近期均赞": m.get("avg_likes"), "近期均评": m.get("avg_comments"),
            "是否商业号": bool(c.get("is_business")), "分类": c.get("category"),
            "简介": c.get("biography"), "外链": c.get("external_url"),
            "内容题材": j.get("内容题材"), "提及工具": j.get("提及工具"), "评论质量标记": j.get("评论质量标记"),
            "来源": j.get("来源", "kol-eval自动"), "抓取时间": today + " 00:00:00", "备注": j.get("备注", ""),
        }
        return IG, patch, "用户ID", pid, c.get("name"), c.get("channel_url") or ""
    if platform == "Twitter":
        c, m = sig["channel"], sig["metrics"]
        pid = c.get("rest_id")
        patch = {
            "账号名称": c.get("name"), "rest_id": pid,
            "主页URL": c.get("channel_url"), "头像URL": c.get("avatar"),
            "粉丝数": c.get("followers"), "关注数": c.get("following"),
            "加权ER": m.get("engagement_rate_weighted"), "点赞率": m.get("like_rate_weighted"),
            "转推率": m.get("retweet_rate_weighted"), "回复率": m.get("reply_rate_weighted"),
            "收藏率": m.get("bookmark_rate_weighted"), "近期均views": m.get("avg_views"),
            "蓝V": bool(c.get("blue_verified")), "认证类型": c.get("verification_type"),
            "创作者国家(自报)": c.get("location"), "简介": c.get("biography"), "外链": c.get("website"),
            "内容题材": j.get("内容题材"), "提及工具": j.get("提及工具"), "评论质量标记": j.get("评论质量标记"),
            "来源": j.get("来源", "kol-eval自动"), "抓取时间": today + " 00:00:00", "备注": j.get("备注", ""),
        }
        return TW, patch, "rest_id", pid, c.get("name"), c.get("channel_url") or ""
    # YouTube
    ch, mt = sig["metrics"]["channel"], sig["metrics"]["metrics"]
    patch = {
        "账号名称": ch.get("name"), "主页URL": ch.get("channel_url"),
        "邮箱": ch.get("email"),
        "创作者国家(自报)": ch.get("creator_country"), "粉丝数": ch.get("subscriber_count"),
        "视频总数": ch.get("total_videos"), "近期均播放": mt.get("avg_views_recent"),
        "中位播放": mt.get("median_views_recent"), "互动率": mt.get("engagement_rate_weighted"),
        "更新间隔": mt.get("upload_interval_days_avg"), "最近更新日期": ch.get("latest_upload"),
        "YouTube分类": ch.get("category"), "内容题材": j.get("内容题材"), "提及工具": j.get("提及工具"),
        "内容语言": j.get("内容语言"),
        "题材_LLM": j.get("题材_LLM"), "调性_LLM": j.get("调性_LLM"),
        "推断受众地区": j.get("推断受众地区"), "受众欧美辐射(推断)": j.get("受众欧美辐射"),
        "评论质量标记": j.get("评论质量标记"), "原始标签": ", ".join(ch.get("raw_tags_top") or []),
        "来源": j.get("来源", "kol-eval自动"),
        "抓取时间": today + " 00:00:00", "备注": j.get("备注", ""),
    }
    return MAIN, patch, "主页URL", ch.get("channel_url"), ch.get("name"), ch.get("channel_url") or ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", required=True)
    ap.add_argument("--judgment", required=True)
    ap.add_argument("--report-dir", default="docs/kol-reports")
    ap.add_argument("--no-write", action="store_true", help="只出报告，不写飞书")
    ap.add_argument("--parent", help="层级认人：把本平台账号挂到该 KOL总表主体 record_id（同一个人的另一平台号）")
    ap.add_argument("--by", help="对接人(email/open_id)：写入 KOL 总表 + 细估完发飞书通知")
    a = ap.parse_args()
    sig = json.load(open(a.signals, encoding="utf-8"))
    j = json.load(open(a.judgment, encoding="utf-8"))
    platform = PLATFORM_OF.get(sig.get("platform"), "YouTube")
    ch, mt, _p, homepage_url = normalize_signals(sig)   # 供报告统一渲染
    today = datetime.date.today().strftime("%Y-%m-%d")

    if not a.no_write:
        validate_enums(j)
        table, patch, idf, idv, name, homepage_url = build_patch(sig, j, platform, today)
        ensure_options(table, "内容题材", j.get("内容题材"))
        ensure_options(table, "提及工具", j.get("提及工具"))
        existing_rid, existing_f = find_in_table(table, idf, idv)
        hub = ensure_hub(name, platform, a.parent, existing_f)
        if hub:
            patch["所属KOL"] = [{"id": hub}]
        patch = {k: v for k, v in patch.items() if v not in (None, "", [])}
        if existing_rid:
            lark(["+record-batch-update", "--base-token", BT, "--table-id", table,
                  "--json", json.dumps({"record_id_list": [existing_rid], "patch": patch}, ensure_ascii=False)])
            rec_rid = existing_rid; action = "更新"
        else:
            # 飞书 batch-create rows 格式会静默丢弃多选数组；先建基础字段，再单独 patch 多选。
            ms = {k: patch.pop(k) for k in list(patch.keys()) if k in MULTI_FIELDS}
            fields = list(patch.keys())
            res = lark(["+record-batch-create", "--base-token", BT, "--table-id", table,
                        "--json", json.dumps({"fields": fields, "rows": [[patch[f] for f in fields]]}, ensure_ascii=False)])
            rec_rid = (res.get("data") or {}).get("record_id_list", [None])[0]; action = "新建"
            if rec_rid and ms:
                lark(["+record-batch-update", "--base-token", BT, "--table-id", table,
                      "--json", json.dumps({"record_id_list": [rec_rid], "patch": ms}, ensure_ascii=False)])
        if hub:
            hub_add_platform(hub, platform)
            HUB_DIMS = ("频道评估", "受众结构", "流量稳定性", "互动真实性", "内容匹配度")
            hub_summary = {k: j[k] for k in HUB_DIMS if j.get(k)}
            hub_summary["合作进度"] = "待联系"
            if a.by:
                hub_summary["对接人"] = a.by
            if hub_summary:
                lark(["+record-batch-update", "--base-token", BT, "--table-id", HUB,
                      "--json", json.dumps({"record_id_list": [hub], "patch": hub_summary}, ensure_ascii=False)])
        print(f"{platform} 明细{action}: {rec_rid} | 挂主体 {hub}")
        # 评估卡 → 关联主体(总表)
        sc = j.get("scores", {})
        ef = ["评估标题", "关联主体", "业务线", "评估阶段", "受众匹配分", "内容承载分", "流量稳定分",
              "互动可信分", "报价合理分", "综合判断", "判断依据", "有效播放", "合理报价区间USD", "计价口径"]
        er = [f"{name} · {platform} · 细估", [{"id": hub}] if hub else None, j.get("业务线"), "细估",
              sc.get("受众匹配"), sc.get("内容承载"), sc.get("流量稳定"), sc.get("互动可信"), sc.get("报价合理"),
              j.get("综合判断"), j.get("判断依据"), j.get("有效播放"), j.get("合理报价区间USD"), j.get("计价口径")]
        r2 = lark(["+record-batch-create", "--base-token", BT, "--table-id", EVAL,
                   "--json", json.dumps({"fields": ef, "rows": [er]}, ensure_ascii=False)])
        print(f"判断卡: {r2.get('ok')} {(r2.get('data') or {}).get('record_id_list')}")

    # 飞书通知对接人
    if not a.no_write and a.by:
        try:
            import feishu_notify as fn
            token = fn.get_tenant_token()
            open_id, id_type = fn.resolve_open_id(token, a.by)
            sc = j.get("scores", {})
            card = fn.build_eval_card(
                title=f"KOL 细估完成: {name}",
                kol_name=name, homepage_url=homepage_url, platform=platform,
                business=j.get("业务线", ""),
                scores=sc, verdict=j.get("综合判断", ""),
                price_range=j.get("合理报价区间USD", ""),
                conclusion=j.get("判断依据", ""),
            )
            fn.send_card(token, open_id, id_type, card)
        except Exception as e:
            print(f"⚠️ 飞书通知失败: {e}", file=sys.stderr)

    # 报告
    rpt = render_report(sig, j, ch, mt, homepage_url, today)
    os.makedirs(a.report_dir, exist_ok=True)
    safe = re.sub(r"[^\w]", "_", ch.get("channel_id") or homepage_url)[:80] or "kol_report"
    path = os.path.join(a.report_dir, f"{safe}.md")
    open(path, "w", encoding="utf-8").write(rpt)
    print(f"报告: {path}")


def fmt_basis(text):
    """把判断依据拆成可读段落：①②③ 圈号要点、**加粗** 关键结论、过渡词各起一段。"""
    if not text:
        return ""
    # 1. 圈号要点：仅在句读(：；。)或行首后断行，避免误拆句中引用的①③
    t = re.sub(r"([：:；;。])\s*([①②③④⑤⑥⑦⑧⑨⑩])\s*", r"\1\n\n\2 ", text.strip())
    # 2. **加粗** 关键论断前加段落（如"**$400 合理**"独立成段）
    t = re.sub(r"[。]\s*(\*\*)", r"。\n\n\1", t)
    # 3. 结构性过渡词（唯一减分/风险/建议合作/建议测试等）前换行
    t = re.sub(r"[。；]\s*(唯一[^\s，。]{0,8}[:：]?)", r"。\n\n\1", t)
    t = re.sub(r"[。；]\s*(建议(合作|测试|观望|放弃|接|拒))", r"。\n\n\1", t)
    t = re.sub(r"[。；]\s*(排期\d)", r"。\n\n\1", t)
    # 4. 明确的标题型词 → 粗体段落标题
    t = re.sub(r"\s*(可推翻点|结论)[:：]", r"\n\n**\1：** ", t)
    return t.strip()


def _c(x):
    return f"{x:,}" if isinstance(x, int) else (x if x is not None else "?")


def render_report(sig, j, ch, mt, homepage_url, today):
    sc = j.get("scores", {})
    platform = {"tiktok": "TikTok", "instagram": "Instagram", "twitter": "Twitter"}.get(sig.get("platform"), "YouTube")
    # 近期Top：兼容 YouTube(title/views) / TikTok(desc/play) / IG(desc/like) / Twitter(text/views)
    raw_top = sig.get("recent_top") or sig.get("metrics", {}).get("recent_top") or []
    top = [{"title": v.get("title") or v.get("desc") or v.get("text"),
            "views": v.get("views") or v.get("play") or v.get("like"),
            "date": v.get("date", ""), "url": v.get("url")} for v in raw_top[:6]]
    cmt = (sig.get("comments") or {}).get("signals", {})       # YouTube
    csig = sig.get("comment_signals", {})                       # TikTok/IG/Twitter
    L = []
    L.append(f"# KOL 评估报告 · {ch.get('name')} [{platform}]\n")
    src = "yt-dlp+/about" if platform == "YouTube" else "TikHub"
    L.append(f"> 评估日期：{today} ｜ 工具：`skills/kol-eval` ｜ 平台：{platform} ｜ 数据来源：{src}")
    L.append(f"> 主页URL：{homepage_url}")
    L.append(f"> 状态：**{j.get('状态','未合作')}**\n\n---\n")
    L.append(f"## 🚦 结论：{j.get('综合判断')}\n")
    L.append(f"**一句话**：{j.get('一句话', j.get('判断依据','')[:80])}\n")
    L.append("| 维度 | 受众匹配 | 内容承载 | 流量稳定 | 互动可信 | 报价合理 |")
    L.append("|---|:--:|:--:|:--:|:--:|:--:|")
    L.append(f"| 分(/10) | {sc.get('受众匹配')} | {sc.get('内容承载')} | {sc.get('流量稳定')} | {sc.get('互动可信')} | {sc.get('报价合理')} |\n")
    L.append(f"- **业务线**：{j.get('业务线')}　**受众欧美辐射**：{j.get('受众欧美辐射')}（{j.get('推断受众地区','')}）")
    L.append(f"- **报价区间**：{j.get('合理报价区间USD','')}（{j.get('计价口径','')}）")
    L.append(f"- **创作者国家(自报)**：{ch.get('creator_country')}\n\n---\n")
    yt = platform == "YouTube"
    L.append("## 1. 基础信息")
    base = "订阅" if yt else "粉丝"
    extra = f" / Shorts {ch.get('shorts_count')}" if yt else (f" ｜ 总赞 {_c(ch.get('total_likes'))}" if ch.get('total_likes') else "")
    cnt = "视频" if platform in ("YouTube", "TikTok") else ("帖" if platform == "Instagram" else "推文")
    L.append(f"- {base} {_c(ch.get('subscriber_count'))}（{ch.get('tier')}）｜ {cnt} {ch.get('total_videos')}{extra}")
    L.append(f"- 分类：{ch.get('category') or '—'} ｜ 题材：{'/'.join(j.get('内容题材',[]))} ｜ 工具：{'/'.join(j.get('提及工具',[]))}\n")
    L.append("## 2. 内容表现（近期 Top，点击跳转）")
    metric_col = {"YouTube": "播放", "TikTok": "播放", "Instagram": "赞", "Twitter": "views"}[platform]
    L.append(f"| {metric_col} | 日期 | 标题/文案 |\n|---:|---|---|")
    for v in top:
        t = str(v.get('title') or '')[:46].replace("|", "\\|")
        L.append(f"| {_c(v['views'])} | {v.get('date','')} | [{t}]({v.get('url','')}) |")
    L.append(f"\n> 近期均{metric_col} {_c(mt.get('avg_views_recent'))}。\n")
    L.append("## 3. 互动质量")
    extra_rate = ""
    if mt.get("share_rate_weighted"):
        extra_rate = f" / {'转发率' if platform=='TikTok' else '转推率'} {mt.get('share_rate_weighted')}"
    base_label = {"YouTube": "播放/订阅", "TikTok": "播放/粉丝"}.get(platform, "")
    ratio = f"｜ {base_label} {mt.get('view_sub_ratio')}" if base_label and mt.get('view_sub_ratio') else ""
    L.append(f"- 加权 ER **{mt.get('engagement_rate_weighted')}**（赞率 {mt.get('like_rate_weighted')} / 评论率 {mt.get('comment_rate_weighted')}{extra_rate}）{ratio}\n")
    L.append("## 4. 评论真实性")
    if platform == "TikTok":
        L.append(f"- 抽样 {csig.get('n_comments','?')} 条 ｜ 语言分布 {csig.get('language_dist')} ｜ 购买意图(原生标记) {csig.get('purchase_intent_count')} ｜ 重复 {csig.get('duplicate_comments')}")
        L.append(f"- 评论质量标记：{j.get('评论质量标记')}\n")
    elif platform in ("Instagram", "Twitter"):
        ld = csig.get("language_dist")
        L.append(f"- {'推文' if platform=='Twitter' else '评论'}语言分布：{ld or '—'} ｜ 评论质量标记：{j.get('评论质量标记')}\n")
    else:
        L.append(f"- 泛灌 {cmt.get('泛泛灌水占比')} ｜ 模板重复 {cmt.get('模板化重复评论占比')} ｜ 0赞 {cmt.get('0赞评论占比')} ｜ 真实观众行为：{cmt.get('真实观众行为提示')}")
        L.append(f"- 评论语言：{cmt.get('评论语言分布(估算)')} ｜ 评论质量标记：{j.get('评论质量标记')}\n")
    L.append("## 5. 判断依据")
    L.append(fmt_basis(j.get("判断依据", "")) + "\n")
    L.append("## 6. 未获取字段")
    missing = sig.get("missing_fields") or sig.get("metrics", {}).get("missing_fields", [])
    L.append("、".join(missing) + "\n")
    return "\n".join(L)


if __name__ == "__main__":
    main()
