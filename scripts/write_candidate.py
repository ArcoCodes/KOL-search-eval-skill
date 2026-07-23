#!/usr/bin/env python3
"""Write Agent rough-screening results to the candidate pool.

This script intentionally does not score or judge a creator. The Agent reads
signals, applies references/rough-eval-rules.md, then passes the resulting
rough judgment here for Feishu persistence.

Usage:
    python3 write_candidate.py --from-search --signals /tmp/sig.json --judgment /tmp/rough_judgment.json --source "discovery:AI video" --keyword "AI video"
    python3 write_candidate.py --from-search --signals - --judgment /tmp/rough_judgment.json --source "discovery:AI video" --keyword "AI video"
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

BT = "WEcDbjFnKa48YbsKa8qc8auQnlc"
POOL = "tblfBV6INxVDVl6X"
SNAPSHOT_FIELDS = ("采集信号JSON", "信号JSON", "信号快照JSON")

VALID_STATUS = {"待细估", "已淘汰(浅筛)"}
ENUM_AUDIENCE = {"欧美为主", "日本为主", "巴西/葡语拉美为主", "分散无主导", "非欧美为主", "未知/待核实"}
ENUM_COMMENT = {"真实讨论", "一般", "严重灌水/疑似养号"}
PLATFORM_OF = {"tiktok": "TikTok", "instagram": "Instagram", "twitter": "Twitter"}


def lark(args):
    r = subprocess.run(["lark-cli", "base", *args, "--as", "user"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "raw": (r.stdout + r.stderr)[:500]}


def list_table(table):
    rows, ids, names, offset = [], [], [], 0
    while True:
        d = (lark(["+record-list", "--base-token", BT, "--table-id", table,
                   "--limit", "200", "--offset", str(offset), "--format", "json"]).get("data") or {})
        if not names:
            names = d.get("fields") or []
        batch = d.get("data") or []
        batch_ids = d.get("record_id_list") or []
        rows.extend(batch)
        ids.extend(batch_ids)
        if not d.get("has_more") or not batch:
            break
        offset += len(batch)
    return [(rid, dict(zip(names, row))) for rid, row in zip(ids, rows)]


def find_in_table(table, id_values):
    values = {v for v in id_values if v}
    if not values:
        return None, None
    for rid, fields in list_table(table):
        if fields.get("平台内ID") in values or fields.get("主页URL") in values:
            return rid, fields
    return None, None


def field_items(table):
    d = lark(["+field-list", "--base-token", BT, "--table-id", table])
    return (d.get("data") or {}).get("items") or (d.get("data") or {}).get("fields") or []


def first_existing_field(table, candidates):
    names = {f.get("name") for f in field_items(table)}
    for name in candidates:
        if name in names:
            return name
    return None


def load_json(path_or_dash):
    if path_or_dash == "-":
        return json.load(sys.stdin)
    with open(path_or_dash, encoding="utf-8") as f:
        return json.load(f)


def extract_signal_summary(sig):
    plat_raw = sig.get("platform")
    if plat_raw in PLATFORM_OF:
        platform = PLATFORM_OF[plat_raw]
        ch = sig.get("channel") or {}
        mt = sig.get("metrics") or {}
        pid = ch.get("sec_uid") or ch.get("user_id") or ch.get("rest_id") or ch.get("unique_id")
        if platform == "TikTok":
            id_value = ch.get("sec_uid") or pid
        elif platform == "Instagram":
            id_value = ch.get("user_id") or pid
        else:
            id_value = ch.get("rest_id") or pid
        return {
            "platform": platform,
            "name": ch.get("name"),
            "url": ch.get("channel_url"),
            "platform_id": id_value,
            "subs": ch.get("followers"),
            "er": mt.get("engagement_rate_weighted"),
            "avg_views": mt.get("avg_play") or mt.get("avg_views") or mt.get("avg_likes"),
            "country": ch.get("region") or ch.get("location"),
        }

    ch = ((sig.get("metrics") or {}).get("channel") or {})
    mt = ((sig.get("metrics") or {}).get("metrics") or {})
    return {
        "platform": "YouTube",
        "name": ch.get("name"),
        "url": ch.get("channel_url"),
        "platform_id": ch.get("channel_id") or ch.get("channel_url"),
        "subs": ch.get("subscriber_count"),
        "er": mt.get("engagement_rate_weighted"),
        "avg_views": mt.get("avg_views_recent"),
        "country": ch.get("creator_country"),
    }


def coerce_business(value, fallback):
    value = value if value is not None else fallback
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return None


def normalize_judgment(judgment):
    status = judgment.get("候选状态") or judgment.get("status")
    if status not in VALID_STATUS:
        passed = judgment.get("passed")
        if isinstance(passed, bool):
            status = "待细估" if passed else "已淘汰(浅筛)"
    if status not in VALID_STATUS:
        raise SystemExit("judgment must include 候选状态/status as 待细估 or 已淘汰(浅筛), or boolean passed")

    score = judgment.get("粗估得分", judgment.get("score"))
    basis = judgment.get("粗估依据") or judgment.get("basis")
    if score is None:
        raise SystemExit("judgment must include 粗估得分 or score")
    if not basis:
        raise SystemExit("judgment must include 粗估依据 or basis")

    return {
        "status": status,
        "score": score,
        "basis": basis,
        "audience": judgment.get("受众辐射(推断)") or judgment.get("audience"),
        "comment_quality": judgment.get("评论质量标记") or judgment.get("comment_quality"),
        "elimination_reason": judgment.get("淘汰原因") or judgment.get("elimination_reason") or "",
        "business": judgment.get("业务线") or judgment.get("business"),
    }


def write_candidate_pool(summary, rough, business, source, keyword, signal_json):
    today = datetime.date.today().strftime("%Y-%m-%d")
    snapshot_field = first_existing_field(POOL, SNAPSHOT_FIELDS)
    patch = {
        "账号名称": summary["name"],
        "平台": [summary["platform"]],
        "主页URL": summary["url"],
        "平台内ID": summary["platform_id"],
        "粉丝数": summary["subs"],
        "加权ER": summary["er"],
        "近期均播放": summary["avg_views"],
        "受众辐射(推断)": rough["audience"] if rough["audience"] in ENUM_AUDIENCE else rough["audience"],
        "评论质量标记": rough["comment_quality"] if rough["comment_quality"] in ENUM_COMMENT else rough["comment_quality"],
        "创作者国家(自报)": summary["country"],
        "粗估得分": rough["score"],
        "粗估依据": rough["basis"],
        "淘汰原因": rough["elimination_reason"],
        "业务线": coerce_business(rough["business"], business),
        "候选状态": rough["status"],
        "发现时间": today + " 00:00:00",
        "来源": source or "agent_rough_eval",
        "命中关键词": keyword or "",
    }
    if snapshot_field:
        patch[snapshot_field] = signal_json
    patch = {k: v for k, v in patch.items() if v not in (None, "", [])}

    rid, _ = find_in_table(POOL, [summary["platform_id"], summary["url"]])
    if rid:
        lark(["+record-batch-update", "--base-token", BT, "--table-id", POOL,
              "--json", json.dumps({"record_id_list": [rid], "patch": patch}, ensure_ascii=False)])
        return rid, "更新"

    fields = list(patch.keys())
    row = [patch[f] for f in fields]
    res = lark(["+record-batch-create", "--base-token", BT, "--table-id", POOL,
                "--json", json.dumps({"fields": fields, "rows": [row]}, ensure_ascii=False)])
    rid = (res.get("data") or {}).get("record_id_list", [None])[0]
    return rid, "新建"


def main():
    ap = argparse.ArgumentParser(description="Agent 粗估结果 → 候选池")
    ap.add_argument("--from-search", action="store_true", help="确认该 KOL 来自 /kol search 发现结果；只有搜索结果允许写候选池")
    ap.add_argument("--signals", required=True, help="signals JSON path, or '-' for stdin")
    ap.add_argument("--judgment", required=True, help="Agent rough judgment JSON path")
    ap.add_argument("--business", help="业务线 fallback: Bloome/EdgeSpark/Renoise")
    ap.add_argument("--source", default="", help="来源标记, e.g. discovery:AI video")
    ap.add_argument("--keyword", default="", help="命中关键词")
    a = ap.parse_args()

    if not a.from_search or not a.source.startswith("discovery:") or not a.keyword.strip():
        raise SystemExit(
            "write_candidate.py 只允许写入 /kol search 发现结果。"
            " 用户直接提供主页URL时必须走 check_kol_exists.py → 细估，不能写候选池。"
            " 如确认为搜索结果，请传 --from-search --source 'discovery:<keywords>' --keyword '<keywords>'。"
        )

    sig = load_json(a.signals)
    judgment = load_json(a.judgment)
    summary = extract_signal_summary(sig)
    rough = normalize_judgment(judgment)
    signal_json = json.dumps(sig, ensure_ascii=False)

    rid, action = write_candidate_pool(summary, rough, a.business, a.source, a.keyword, signal_json)
    print(json.dumps({
        "ok": True,
        "action": action,
        "record_id": rid,
        "name": summary["name"],
        "platform": summary["platform"],
        "status": rough["status"],
        "score": rough["score"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
