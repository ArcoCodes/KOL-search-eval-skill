#!/usr/bin/env python3
"""飞书 IM 消息发送（自建应用）。

用 app_id + app_secret 获取 tenant_access_token，
然后通过 IM API 给个人发送消息卡片。

用法:
    python3 feishu_notify.py --to <open_id|email> --title "细估完成" --body "报告内容..."
    python3 feishu_notify.py --to user@example.com --card /tmp/card.json

Key 读取: 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET，或 scripts/.env 中配置。
"""
import argparse, json, os, sys, urllib.request, urllib.error

BASE = "https://open.feishu.cn/open-apis"


def _read_env():
    cfg = {}
    envp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def _get_key(name):
    return os.environ.get(name) or _read_env().get(name)


def get_tenant_token():
    app_id = _get_key("FEISHU_APP_ID")
    app_secret = _get_key("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise SystemExit("❌ 未配置 FEISHU_APP_ID / FEISHU_APP_SECRET（环境变量或 scripts/.env）")
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/v3/tenant_access_token/internal/",
        data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    if d.get("code") != 0:
        raise SystemExit(f"❌ 获取 tenant_access_token 失败: {d}")
    return d["tenant_access_token"]


def resolve_open_id(token, identifier):
    """email/mobile → open_id。如果已经是 ou_ 开头直接返回。"""
    if identifier.startswith("ou_"):
        return identifier, "open_id"
    id_type = "email" if "@" in identifier else "mobile"
    body = json.dumps({f"{id_type}s": [identifier]}).encode()
    req = urllib.request.Request(
        f"{BASE}/contact/v3/users/batch_get_id?user_id_type=open_id",
        data=body, headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        })
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    users = (d.get("data") or {}).get("user_list") or []
    if users and users[0].get("user_id"):
        return users[0]["user_id"], "open_id"
    raise SystemExit(f"❌ 无法解析用户 {identifier}: {d}")


def send_message(token, receive_id, receive_id_type, msg_type, content):
    body = json.dumps({
        "receive_id": receive_id,
        "msg_type": msg_type,
        "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/im/v1/messages?receive_id_type={receive_id_type}",
        data=body, headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
        if d.get("code") != 0:
            print(f"⚠️ 发送失败: {d}", file=sys.stderr)
            return False
        msg_id = (d.get("data") or {}).get("message_id")
        print(f"✅ 消息已发送: {msg_id}", file=sys.stderr)
        return True
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        return False


def build_eval_card(title, kol_name, homepage_url, platform, business,
                    scores, verdict, price_range, conclusion, report_url=None):
    """构建细估报告消息卡片。"""
    score_text = " | ".join(f"{k} **{v}**" for k, v in scores.items())
    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**KOL**: {kol_name}\n**主页URL**: {homepage_url}\n**平台**: {platform} | **业务线**: {business}"}},
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**评分**: {score_text}"}},
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**判断**: {verdict}\n**报价**: {price_range}"}},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": conclusion[:500]}},
    ]
    if report_url:
        elements.append({
            "tag": "action",
            "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "查看完整报告"},
                         "type": "primary", "url": report_url}]
        })
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title},
                   "template": "green" if verdict == "建议合作" else ("orange" if verdict == "观望" else "red")},
        "elements": elements,
    }


def send_text(token, receive_id, receive_id_type, text):
    return send_message(token, receive_id, receive_id_type, "text",
                        json.dumps({"text": text}, ensure_ascii=False))


def send_card(token, receive_id, receive_id_type, card):
    return send_message(token, receive_id, receive_id_type, "interactive",
                        json.dumps(card, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="飞书 IM 消息发送")
    ap.add_argument("--to", required=True, help="收件人: open_id(ou_xxx) / email / 手机号")
    ap.add_argument("--title", default="KOL 细估报告", help="卡片标题")
    ap.add_argument("--body", help="纯文本消息内容")
    ap.add_argument("--card", help="消息卡片 JSON 文件路径")
    a = ap.parse_args()

    token = get_tenant_token()
    open_id, id_type = resolve_open_id(token, a.to)

    if a.card:
        card = json.load(open(a.card, encoding="utf-8"))
        send_card(token, open_id, id_type, card)
    elif a.body:
        send_text(token, open_id, id_type, a.body)
    else:
        print("请指定 --body 或 --card", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
