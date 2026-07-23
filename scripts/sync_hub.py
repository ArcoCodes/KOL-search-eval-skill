#!/usr/bin/env python3
"""刷新 KOL总表(dashboard)：从子记录(评估卡/批次/各平台明细)汇总到主体的 综合判断/合作进度/
统一邮箱，并盖 状态更新时间。只填空字段，不覆盖人工编辑。随时可重跑批量补齐。
4维摘要(受众结构/流量稳定性/互动真实性/内容匹配度)由 write_kol.py 评估时直接写 hub。"""
import json,subprocess,datetime
BT="WEcDbjFnKa48YbsKa8qc8auQnlc"
NOW=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
HUB="tblEylVlrP1Qtrmb";MAIN="tblzR7h4fH1y1Hkf";EVAL="tblA1p25lxwHnsuV";BATCH="tblqZBeOlkxpYkd1"
HUB_PROG={"待联系","建联中","砍价中","已成交","制作中","已上线","流失","搁置"}
BMAP={"待邀约":"待联系","已邀约":"建联中","已回复":"建联中"}  # 批次状态→合作进度其余同名
def lark(a):
    r=subprocess.run(["lark-cli","base",*a,"--as","user"],capture_output=True,text=True)
    try:return json.loads(r.stdout)
    except:
        try:return json.loads(r.stderr)
        except:return {"ok":False,"raw":(r.stdout+r.stderr)[:200]}
def tbl(t):
    out=[];off=0   # 全量翻页：总表/评估表已 360+ 行，单页 200 会漏掉后半截
    while True:
        d=lark(["+record-list","--base-token",BT,"--table-id",t,"--limit","200","--offset",str(off),"--format","json"]).get("data",{})
        n=d.get("fields",[])
        out+=[(rid,dict(zip(n,row))) for rid,row in zip(d.get("record_id_list",[]),d.get("data",[]))]
        if not d.get("has_more"):break
        off+=200
    return out
def sc(v):return v[0] if isinstance(v,list) and v and isinstance(v[0],str) else v
def lids(v):return [x.get("id") for x in v if isinstance(x,dict) and x.get("id")] if isinstance(v,list) else []

hubs=tbl(HUB); yt=tbl(MAIN); ev=tbl(EVAL); bt=tbl(BATCH)
# YouTube rid → {邮箱,hub}
yt_info={rid:{"邮箱":f.get("邮箱"),"hub":(lids(f.get("所属KOL")) or [None])[0]} for rid,f in yt}
# hub → 评估(综合判断,依据)
hub_eval={}
for rid,f in ev:
    zj=sc(f.get("综合判断")); ev_basis=f.get("判断依据")
    hub_rids=set(lids(f.get("关联主体")))   # 评估卡统一挂主体(关联KOL 旧字段已删，已回填)
    for h in hub_rids:
        if zj or ev_basis: hub_eval.setdefault(h,[]).append((zj,ev_basis))
# hub → 批次状态
hub_batch={}
for rid,f in bt:
    st=sc(f.get("批次状态"))
    for h in lids(f.get("关联KOL主体")): 
        if st: hub_batch[h]=st
# YouTube账号 → 邮箱 经 hub
hub_yt={}  # hub → (邮箱)
for ytr,info in yt_info.items():
    if info["hub"]: hub_yt.setdefault(info["hub"],info)

SUMMARY_DIMS=["受众结构","流量稳定性","互动真实性","内容匹配度"]
filled={"综合判断":0,"合作进度":0,"统一邮箱":0}
filled.update({d:0 for d in SUMMARY_DIMS})
for rid,f in hubs:
    patch={}
    if not sc(f.get("综合判断")) and hub_eval.get(rid):
        zj=next((z for z,_ in hub_eval[rid] if z),None)
        if zj: patch["综合判断"]=zj
    if not sc(f.get("合作进度")):
        prog=None
        if rid in hub_batch:
            bs=hub_batch[rid]; prog=BMAP.get(bs, bs if bs in HUB_PROG else None)
        if not prog:
            prog = "待联系"   # 无批次状态可推 → 默认待联系（YT 当前状态字段已废除）
        patch["合作进度"]=prog
    if not f.get("统一邮箱"):
        em=hub_yt.get(rid,{}).get("邮箱")
        if em: patch["统一邮箱"]=em
    # 有状态(综合判断/合作进度)且缺时间戳 → 补盖；本次有回填 → 也盖
    has_status=any([sc(f.get("综合判断")),patch.get("综合判断"),sc(f.get("合作进度")),patch.get("合作进度")])
    if patch or (has_status and not f.get("状态更新时间")):
        patch["状态更新时间"]=NOW
        lark(["+record-batch-update","--base-token",BT,"--table-id",HUB,
          "--json",json.dumps({"record_id_list":[rid],"patch":patch},ensure_ascii=False)])
        for k in patch:
            if k!="状态更新时间": filled[k]=filled.get(k,0)+1
print("回填:",filled,"| 状态更新时间盖章:",NOW,"| 总表",len(hubs),"行")
