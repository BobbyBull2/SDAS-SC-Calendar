#!/usr/bin/env python3
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "events.json"
DISCORD_DATA = ROOT / "discord-events.json"
PIPELINE_DATA = ROOT / "pipeline-candidates.json"
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

def local_ics(value):
    dt=datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(ZoneInfo("America/Chicago"))
    return dt.strftime("%Y%m%dT%H%M%S")

def discord_rrule(rule):
    if not rule:
        return None
    freq_map={0:"YEARLY",1:"MONTHLY",2:"WEEKLY",3:"DAILY"}
    day_map={0:"MO",1:"TU",2:"WE",3:"TH",4:"FR",5:"SA",6:"SU"}
    freq=freq_map.get(rule.get("frequency"))
    if not freq:
        return None
    parts=[f"FREQ={freq}"]
    interval=rule.get("interval") or 1
    if interval != 1:
        parts.append(f"INTERVAL={interval}")
    weekdays=rule.get("by_weekday") or []
    # For simple weekly recurrence, DTSTART is the safest cross-calendar anchor.
    # Omitting BYDAY avoids UTC/local weekday splits (e.g. Wed evening CDT = Thu UTC).
    if weekdays and freq != "WEEKLY":
        days=[day_map[d] for d in weekdays if d in day_map]
        if days:
            parts.append("BYDAY="+",".join(days))
    nweek=rule.get("by_n_weekday") or []
    if nweek:
        days=[f'{x["n"]}{day_map[x["day"]]}' for x in nweek if x.get("day") in day_map and x.get("n")]
        if days:
            parts.append("BYDAY="+",".join(days))
    months=rule.get("by_month") or []
    if months:
        parts.append("BYMONTH="+",".join(str(x) for x in months))
    mdays=rule.get("by_month_day") or []
    if mdays:
        parts.append("BYMONTHDAY="+",".join(str(x) for x in mdays))
    if rule.get("count"):
        parts.append(f'COUNT={rule["count"]}')
    if rule.get("end"):
        parts.append("UNTIL="+utc_ics(rule["end"]))
    return ";".join(parts)

data=json.loads(DATA.read_text(encoding="utf-8"))
events=data["events"]
discord_events=[]
if DISCORD_DATA.exists():
    discord_events=json.loads(DISCORD_DATA.read_text(encoding="utf-8")).get("events", [])
pipeline_events=[]
if PIPELINE_DATA.exists():
    pipeline_events=json.loads(PIPELINE_DATA.read_text(encoding="utf-8")).get("published", [])

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

for e in pipeline_events:
    dates=e.get("dates") or []
    if not dates or not e.get("stable_key"):
        continue
    start=dates[0]
    end=(datetime.fromisoformat(start)+timedelta(days=1)).date().isoformat()
    cls=e.get("classification","EVENT_REVIEW")
    prefix="[PTU]" if "PTU" in cls else ("[PATCH]" if "LIVE" in cls else "[CIG]")
    key=e["stable_key"]
    title=key.replace("-"," ").title()
    if key.startswith("patch-"):
        parts=key.split("-")
        version=parts[1]
        title=f"Star Citizen {version} "+("PTU" if parts[-1]=="ptu" else "LIVE")
    source=e.get("official_rsi_source") or e.get("discord_source")
    desc="CIG/PIPELINE dated announcement"
    if source: desc += "\\nSource: "+source
    lines += ["BEGIN:VEVENT",f"UID:pipeline-{key}@sdas-star-citizen",f"DTSTAMP:{stamp}",
              f"DTSTART;VALUE=DATE:{ymd(start)}",f"DTEND;VALUE=DATE:{ymd(end)}",
              f"SUMMARY:{esc(prefix+' '+title)}",f"DESCRIPTION:{esc(desc)}"]
    if source: lines.append(f"URL:{source}")
    lines += ["TRANSP:TRANSPARENT","END:VEVENT"]

for e in discord_events:
    if not e.get("id") or not e.get("start"):
        continue
    start=local_ics(e["start"])
    if e.get("end"):
        end=local_ics(e["end"])
    else:
        local_start=datetime.fromisoformat(e["start"].replace("Z","+00:00")).astimezone(ZoneInfo("America/Chicago"))
        end=(local_start + timedelta(hours=4)).strftime("%Y%m%dT%H%M%S")
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
              f"DTSTART;TZID=America/Chicago:{start}",f"DTEND;TZID=America/Chicago:{end}",
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
print(f"Generated {OUT.name}: {len(events)} CIG/RSI + {len(pipeline_events)} dated PIPELINE + {len(discord_events)} SDAS Discord events")
