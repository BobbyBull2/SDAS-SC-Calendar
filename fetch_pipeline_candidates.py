#!/usr/bin/env python3
import json, os, re, urllib.request
from datetime import datetime, timezone
from pathlib import Path

GUILD_ID="1518410019249459236"
CHANNEL_ID=os.environ.get("DISCORD_GAME_NEWS_CHANNEL_ID","1519103965290168560")
TOKEN=os.environ.get("DISCORD_BOT_TOKEN")
OUT=Path(__file__).resolve().parent/"pipeline-candidates.json"
if not TOKEN: raise SystemExit("DISCORD_BOT_TOKEN is not set")

req=urllib.request.Request(
    f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages?limit=50",
    headers={"Authorization":f"Bot {TOKEN}","User-Agent":"SDAS-Calendar-Sync/1.0"})
with urllib.request.urlopen(req,timeout=30) as r: raw=json.load(r)

MONTHS={m.lower():i for i,m in enumerate(
 ["January","February","March","April","May","June","July","August","September","October","November","December"],1)}
MONTH_RE="|".join(MONTHS)
DATE_PATTERNS=[
 re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d{{2}}))?\b",re.I),
 re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
]

def explicit_dates(text, fallback_year):
    out=[]
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            if m.re is DATE_PATTERNS[0]:
                y=int(m.group(3) or fallback_year); mo=MONTHS[m.group(1).lower()]; d=int(m.group(2))
            else:
                y,mo,d=map(int,m.groups())
            try: out.append(datetime(y,mo,d).date().isoformat())
            except ValueError: pass
    return sorted(set(out))

def classify(text):
    s=text.lower()
    if "#star-citizen-leaks" in s or "leak" in s: return "IGNORE_LEAK"
    if "potential" in s or "possibly" in s or "expected" in s: return "EXPECTED"
    if "patch notes" in s and ("ptu" in s or "eptu" in s): return "PTU_CONFIRMED"
    live_confirmed=(
        "now live" in s or
        "is now live" in s or
        "released to live" in s or
        "live patch notes" in s or
        "live release notes" in s
    )
    if live_confirmed and ("patch" in s or "release" in s): return "LIVE_CONFIRMED"
    if any(x in s for x in ("free fly","iae","invictus","alien week","pirate week","luminalia","day of the vara")): return "EVENT_REVIEW"
    return "IGNORE_NEWS"

def stable_key(text, cls):
    version=re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b",text)
    if version and cls in ("PTU_CONFIRMED","LIVE_CONFIRMED","EXPECTED"):
        lane="ptu" if "PTU" in cls or "ptu" in text.lower() or "eptu" in text.lower() else "live"
        return f"patch-{version.group(1)}-{lane}"
    for key,label in (("free fly","free-fly"),("iae","iae"),("invictus","invictus"),("alien week","alien-week"),("pirate week","pirate-week"),("luminalia","luminalia"),("day of the vara","day-of-the-vara")):
        if key in text.lower(): return label
    return None

items=[]
for m in raw:
    content=(m.get("content") or "").strip()
    embeds=m.get("embeds") or []
    extra="\n".join(str(x) for e in embeds for x in (e.get("title"),e.get("description"),e.get("url")) if x)
    text=(content+"\n"+extra).strip()
    if not text: continue
    cls=classify(text)
    ts=m.get("timestamp") or datetime.now(timezone.utc).isoformat()
    year=datetime.fromisoformat(ts.replace("Z","+00:00")).year
    dates=explicit_dates(text,year)
    urls=re.findall(r'https?://[^)>\s]+',text)
    official=next((u for u in urls if "robertsspaceindustries.com" in u),None)
    key=stable_key(text,cls)
    publish=bool(dates and key and cls not in ("IGNORE_LEAK","IGNORE_NEWS"))
    items.append({
      "message_id":str(m["id"]),"timestamp":m.get("timestamp"),"classification":cls,
      "stable_key":key,"dates":dates,"auto_publish":publish,
      "official_rsi_source":official,
      "discord_source":f"https://discord.com/channels/{GUILD_ID}/{CHANNEL_ID}/{m['id']}",
      "content":text
    })

# Newest message wins for each stable event identity. A later dated post therefore moves the event.
published={}
for x in sorted(items,key=lambda z:z.get("timestamp") or ""):
    if x["auto_publish"]: published[x["stable_key"]]=x

OUT.write_text(json.dumps({"channel_id":CHANNEL_ID,"fetched_at":datetime.now(timezone.utc).isoformat(),
 "policy":"Explicitly dated CIG/PIPELINE items may publish. Newer posts replace dates for the same stable event identity.",
 "published":list(published.values()),"candidates":items},indent=2)+"\n",encoding="utf-8")
counts={}
for x in items: counts[x["classification"]]=counts.get(x["classification"],0)+1
print("PIPELINE classifications:",counts)
print("Dated events selected:",len(published))
for x in published.values(): print("-",x["stable_key"],x["dates"],x["classification"])
