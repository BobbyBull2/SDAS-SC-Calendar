#!/usr/bin/env python3
import json, hashlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "events.json"
OUT = ROOT / "star-citizen-events.ics"

def esc(s):
    return str(s).replace("\\","\\\\").replace(",","\\,").replace(";","\\;").replace("\n","\\n")

def fold(line, limit=73):
    out=[]
    while len(line)>limit:
        out.append(line[:limit])
        line=" "+line[limit:]
    out.append(line)
    return "\r\n".join(out)

def ymd(value):
    return value.replace("-","")

data=json.loads(DATA.read_text(encoding="utf-8"))
events=data["events"]
stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
lines=[
"BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//SDAS//Star Citizen Events//EN",
"CALSCALE:GREGORIAN","METHOD:PUBLISH",
f'X-WR-CALNAME:{esc(data["calendar"]["name"])}',
f'X-WR-CALDESC:{esc(data["calendar"]["description"])}',
"REFRESH-INTERVAL;VALUE=DURATION:P1D","X-PUBLISHED-TTL:P1D"
]
seen=set()
for e in events:
    for key in ("title","start","end","status","description"):
        if key not in e: raise ValueError(f"Missing {key}: {e}")
    if e["end"] <= e["start"]: raise ValueError(f'End must follow start: {e["title"]}')
    ident=e["title"]+"|"+e["start"]
    if ident in seen: raise ValueError(f"Duplicate event: {ident}")
    seen.add(ident)
    uid=hashlib.sha1(ident.encode()).hexdigest()[:20]+"@sdas-star-citizen"
    summary=e["title"] if e["status"]=="CONFIRMED" else f'[{e["status"]}] {e["title"]}'
    lines += ["BEGIN:VEVENT",f"UID:{uid}",f"DTSTAMP:{stamp}",
              f'DTSTART;VALUE=DATE:{ymd(e["start"])}',f'DTEND;VALUE=DATE:{ymd(e["end"])}',
              f"SUMMARY:{esc(summary)}",f'DESCRIPTION:{esc(e["status"]+" — "+e["description"])}',
              "TRANSP:TRANSPARENT","END:VEVENT"]
lines.append("END:VCALENDAR")
OUT.write_text("\r\n".join(fold(x) for x in lines)+"\r\n",encoding="utf-8",newline="")
print(f"Generated {OUT.name}: {len(events)} events")
