#!/usr/bin/env python3
"""细估入口预处理：先查系统是否已存在，再复用候选池信息或重采。

用法:
    python3 check_kol_exists.py <homepage_url> --out /tmp/sig.json
    python3 check_kol_exists.py <homepage_url> --out /tmp/sig.json --meta-out /tmp/kol_lookup.json

行为:
  1. 先按主页URL检查平台明细/KOL总表是否已存在
  2. 若已存在于正式系统，返回 exists_in_system，提醒不要重复细估
  3. 否则检查候选池；若命中则把候选状态改为已通过，并返回该行全部字段
  4. 候选池有信号快照则直接复用；没有快照则重新采信号
  5. 若候选池中不存在，则重新采信号，直接进入细估，不写候选池
"""
import argparse
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

BT = "WEcDbjFnKa48YbsKa8qc8auQnlc"
POOL = "tblfBV6INxVDVl6X"
TABLES = {
    "YouTube": "tblzR7h4fH1y1Hkf",
    "TikTok": "tblsUnmLnBVfXpEg",
    "Instagram": "tblV1DXvLLoci6ZM",
    "Twitter": "tbltybPG07lSIuqM",
}
SNAPSHOT_FIELDS = ("采集信号JSON", "信号JSON", "信号快照JSON")


def lark(args):
    r = subprocess.run(["lark-cli", "base", *args, "--as", "user"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "raw": (r.stdout + r.stderr)[:300]}


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


def link_first(cell):
    return cell[0]["id"] if isinstance(cell, list) and cell and isinstance(cell[0], dict) else None


def detect_platform(target):
    if "instagram.com" in target:
        return "Instagram"
    if "tiktok.com" in target:
        return "TikTok"
    if "twitter.com" in target or "x.com" in target:
        return "Twitter"
    if "youtube.com" in target or "youtu.be" in target:
        return "YouTube"
    raise SystemExit("只支持 KOL 主页URL，请提供 YouTube / TikTok / Instagram / X 的主页链接。")


def normalize_url(url):
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def extract_account_from_url(target, platform):
    parsed = urlparse(target)
    parts = [p for p in parsed.path.split("/") if p]
    if platform == "YouTube":
        return target
    if platform in {"TikTok", "Instagram", "Twitter"}:
        if not parts:
            raise SystemExit("主页URL缺少账号路径，无法采集信号。")
        return parts[0].lstrip("@")
    return target


def find_existing_system(url):
    normalized = normalize_url(url)
    for platform, table in TABLES.items():
        for rid, fields in list_table(table):
            value = fields.get("主页URL")
            if isinstance(value, str) and normalize_url(value) == normalized:
                return {
                    "platform": platform,
                    "table": table,
                    "record_id": rid,
                    "hub_id": link_first(fields.get("所属KOL")),
                    "name": fields.get("账号名称"),
                }
    return None


def find_candidate(url):
    normalized = normalize_url(url)
    for rid, fields in list_table(POOL):
        value = fields.get("主页URL")
        if isinstance(value, str) and normalize_url(value) == normalized:
            return rid, fields
    return None, None


def update_candidate_status(record_id, status):
    return lark(["+record-batch-update", "--base-token", BT, "--table-id", POOL,
                 "--json", json.dumps({"record_id_list": [record_id],
                                       "patch": {"候选状态": status}}, ensure_ascii=False)])


def parse_snapshot(fields):
    for field in SNAPSHOT_FIELDS:
        raw = fields.get(field)
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw), field
            except json.JSONDecodeError:
                return None, field
    return None, None


def collect_signals(target, platform):
    account = extract_account_from_url(target, platform)
    base = os.path.dirname(os.path.abspath(__file__))
    if platform == "YouTube":
        cmd = ["python3", os.path.join(base, "data_scrawl", "youtube_data.py"), account,
               "--n", "8", "--comment-videos", "4"]
    elif platform == "TikTok":
        cmd = ["python3", os.path.join(base, "data_scrawl", "tiktok_data.py"), "analyze", target]
    elif platform == "Instagram":
        cmd = ["python3", os.path.join(base, "data_scrawl", "instagram_data.py"), "analyze", target]
    else:
        cmd = ["python3", os.path.join(base, "data_scrawl", "twitter_data.py"), "analyze", target]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(res.stderr.strip() or res.stdout.strip() or f"采信号失败: {' '.join(cmd)}")
    return json.loads(res.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="KOL主页URL")
    ap.add_argument("--out", help="把最终 signals JSON 写到指定文件")
    ap.add_argument("--meta-out", help="把查重结果和候选池行信息写到指定 JSON（不包含 signals 大字段）")
    a = ap.parse_args()

    if not a.target.startswith("http"):
        raise SystemExit("只支持 KOL 主页URL，不支持账号名或其他非URL输入。")

    platform = detect_platform(a.target)
    result = {"target": a.target, "platform": platform}

    existing = find_existing_system(a.target)
    if existing:
        result.update({
            "status": "exists_in_system",
            "message": "该主页URL已存在于正式系统，请先确认是否需要重复细估。",
            "existing": existing,
        })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    pool_rid, pool_fields = find_candidate(a.target)
    if pool_rid:
        previous_status = pool_fields.get("候选状态")
        status_update = update_candidate_status(pool_rid, "已通过")
        pool_fields["候选状态"] = "已通过"
        sig, snapshot_field = parse_snapshot(pool_fields)
        result["candidate_pool"] = {
            "record_id": pool_rid,
            "previous_status": previous_status,
            "status": "已通过",
            "snapshot_field": snapshot_field,
            "status_update_ok": status_update.get("ok"),
            "fields": pool_fields,
        }
        if sig is not None:
            result["status"] = "candidate_snapshot"
            result["message"] = "候选池已存在该主页URL，候选状态已改为已通过；直接复用信号快照进入细估。"
            result["signals"] = sig
        else:
            result["status"] = "candidate_refetch"
            result["message"] = "候选池已存在该主页URL，候选状态已改为已通过；没有可用信号快照，重新采信号后进入细估。"
            result["signals"] = collect_signals(a.target, platform)
    else:
        result["status"] = "refetched"
        result["message"] = "KOL总表和候选池都不存在该主页URL，已采信号；直接进入细估，不写候选池。"
        result["signals"] = collect_signals(a.target, platform)

    if a.out and result.get("signals") is not None:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result["signals"], f, ensure_ascii=False, indent=2)
        result["signals_out"] = a.out

    if a.meta_out:
        meta = dict(result)
        meta.pop("signals", None)
        with open(a.meta_out, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        result["meta_out"] = a.meta_out

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
