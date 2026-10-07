#!/usr/bin/env python3
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "events.json"
DISCORD_DATA = ROOT / "discord-events.json"
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

def utc_ics(value):
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

data=json.loads(DATA.read_text(encoding="utf-8"))
events=data["events"]
discord_events=[]
if DISCORD_DATA.exists():
    discord_events=json.loads(DISCORD_DATA.read_text(encoding="utf-8")).get("events", [])

stamp="20261005T180000Z"
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
    uid="".join(c.lower() if c.isalnum() else "-" for c in e["title"]).strip("-")+"@sdas-star-citizen"
    summary=e["title"] if e["status"]=="CONFIRMED" else f'[{e["status"]}] {e["title"]}'
    lines += ["BEGIN:VEVENT",f"UID:{uid}",f"DTSTAMP:{stamp}",
              f'DTSTART;VALUE=DATE:{ymd(e["start"])}',f'DTEND;VALUE=DATE:{ymd(e["end"])}',
              f"SUMMARY:{esc(summary)}",f'DESCRIPTION:{esc(e["status"]+" — "+e["description"])}',
              "TRANSP:TRANSPARENT","END:VEVENT"]

for e in discord_events:
    if not e.get("id") or not e.get("start"):
        continue
    start=utc_ics(e["start"])
    end=utc_ics(e["end"]) if e.get("end") else (datetime.fromisoformat(e["start"].replace("Z","+00:00")).astimezone(timezone.utc) + timedelta(hours=4)).strftime("%Y%m%dT%H%M%SZ")
    source=e.get("source")
    desc_parts=["SDAS Discord Scheduled Event"]
    if e.get("description"):
        desc_parts += ["", e["description"]]
    if e.get("location"):
        desc_parts += ["", "Location: "+e["location"]]
    if source:
        desc_parts += ["", "View event in Discord: "+source]
    desc="\n".join(desc_parts)
    lines += ["BEGIN:VEVENT",f'UID:discord-{e["id"]}@sdas-star-citizen',f"DTSTAMP:{stamp}",
              f"DTSTART:{start}",f"DTEND:{end}",
              f'SUMMARY:{esc("[SDAS] "+e.get("title","SDAS Event"))}',
              f"DESCRIPTION:{esc(desc)}"]
    recurrence=discord_rrule(e.get("recurrence_rule"))
    if recurrence:
        lines.append(f"RRULE:{recurrence}")
    if e.get("location"):
        lines.append(f'LOCATION:{esc(e["location"])}')
    if source:
        lines.append(f"URL:{source}")
    lines += ["TRANSP:TRANSPARENT","END:VEVENT"]

lines.append("END:VCALENDAR")
OUT.write_text("\r\n".join(fold(x) for x in lines)+"\r\n",encoding="utf-8",newline="")
print(f"Generated {OUT.name}: {len(events)} CIG/RSI + {len(discord_events)} SDAS Discord events")
