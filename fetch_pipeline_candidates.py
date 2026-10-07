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

def classify(text):
    s=text.lower()
    if "#star-citizen-leaks" in s or "leak" in s: return "IGNORE_LEAK"
    if "potential" in s or "possibly" in s or "expected" in s: return "EXPECTED"
    if "patch notes" in s and ("ptu" in s or "eptu" in s):
        return "PTU_CONFIRMED"
    if "live" in s and ("patch" in s or "release" in s):
        return "LIVE_CONFIRMED"
    if any(x in s for x in ("free fly","iae","invictus","alien week","pirate week","luminalia","day of the vara")):
        return "EVENT_REVIEW"
    return "IGNORE_NEWS"

items=[]
for m in raw:
    content=(m.get("content") or "").strip()
    embeds=m.get("embeds") or []
    extra="\n".join(str(x) for e in embeds for x in (e.get("title"),e.get("description"),e.get("url")) if x)
    text=(content+"\n"+extra).strip()
    if not text: continue
    cls=classify(text)
    urls=re.findall(r'https?://[^)>\s]+',text)
    official=next((u for u in urls if "robertsspaceindustries.com" in u),None)
    items.append({
      "message_id":str(m["id"]),"timestamp":m.get("timestamp"),"classification":cls,
      "auto_publish":False,"official_rsi_source":official,
      "discord_source":f"https://discord.com/channels/{GUILD_ID}/{CHANNEL_ID}/{m['id']}",
      "content":text
    })

OUT.write_text(json.dumps({"channel_id":CHANNEL_ID,"fetched_at":datetime.now(timezone.utc).isoformat(),
 "policy":"PIPELINE is intelligence only; no candidate auto-publishes until date extraction and official-source validation are implemented.",
 "candidates":items},indent=2)+"\n",encoding="utf-8")
counts={}
for x in items: counts[x["classification"]]=counts.get(x["classification"],0)+1
print("PIPELINE classifications:",counts)
print("Auto-published: 0")
