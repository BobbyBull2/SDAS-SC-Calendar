# SDAS Star Citizen Calendar

A subscribable Star Citizen events calendar for Google Calendar, Apple Calendar, Outlook, and other iCalendar clients.

## Subscribe

Use the raw `star-citizen-events.ics` URL from the `main` branch as your calendar subscription URL.

## Maintaining events

Edit `events.json` rather than editing the generated ICS file directly.

Statuses:
- **CONFIRMED** — exact dates published/verified from CIG/RSI.
- **TENTATIVE** — expected or placeholder dates awaiting confirmation.
- **ANNUAL** — established annual lore/calendar date where the wider promotional window may vary.

After `events.json` changes on `main`, GitHub Actions runs `generate_calendar.py`, validates the result, and commits `star-citizen-events.ics` if it changed. The workflow also runs daily and can be triggered manually.

> The scheduled job rebuilds and validates the calendar; it does not scrape rumors or automatically promote tentative dates to confirmed.
