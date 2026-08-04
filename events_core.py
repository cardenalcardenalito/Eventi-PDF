"""
events_core.py

Shared logic for turning an events CSV into formatted HTML, ready to be
converted to PDF. Used by both the command-line script and the web app,
so the layout only has to be maintained in one place.
"""

import csv
import html
import io
import re
from datetime import datetime

from dateutil import parser as dateparser

IT_DAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
IT_MONTHS = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
             "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

# Italian words that stay lowercase in a title, unless they're the first word
IT_LOWER_WORDS = {
    "di", "del", "della", "dei", "degli", "delle", "e", "a", "al", "alla",
    "ai", "agli", "da", "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "in", "nel", "nello", "nella", "nei", "negli", "nelle",
    "con", "col", "coi", "su", "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "per", "tra", "fra", "il", "lo", "la", "i", "gli", "le",
    "un", "uno", "una", "d", "l", "o", "ma", "non",
}

CSS = """
@page {
    size: A4;
    margin: 10mm 7mm 20mm 7mm;
}
body {
    font-family: "DejaVu Sans", Arial, sans-serif;
    color: #1a1a1a;
    font-size: 10.5pt;
    line-height: 1.35;
}
.header {
    text-align: center;
    margin-bottom: 22px;
}
.header .logos {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 20px;
    margin-bottom: 10px;
}
.header .logos img {
    height: 65px;
}
.header h1 {
    font-size: 16pt;
    font-weight: bold;
    margin: 0;
}
.day-block {
    margin-top: 22px;
    margin-left: 0px;
    margin-right: 0px;
}
.day-block:first-of-type {
    margin-top: 0;
}
.day-header {
    background: #dcdcdc;
    font-weight: bold;
    font-size: 12pt;
    text-align: left;
    padding: 1px 3px;
    margin: 0 0 8px 0;
    break-after: avoid;
    page-break-after: avoid;
}
.day-events {
    margin-left: 110px;
}
.event {
    padding: 12px 0;
    border-bottom: 1px solid #cfcfcf;
    break-inside: avoid;
    page-break-inside: avoid;
}
.day-events .event:last-child {
    border-bottom: none;
}
.event-row {
    display: table;
    width: 100%;
    table-layout: fixed;
}
.title-cell, .time-cell, .place-cell {
    display: table-cell;
    vertical-align: top;
}
.title-cell {
    width: 52%;
    font-weight: bold;
    font-size: 11.5pt;
    text-align: left;
}
.time-cell {
    width: 15%;
    font-weight: bold;
    text-align: left;
    white-space: nowrap;
}
.place-cell {
    width: 33%;
    font-weight: bold;
    text-align: left;
}
.icon {
    display: inline-block;
    width: 12px;
    height: 12px;
    vertical-align: -1px;
    margin-right: 6px;
}
.time-line {
    white-space: nowrap;
}
.description {
    margin-top: 16px;
    font-size: 10pt;
    color: #262626;
}
.organizer {
    margin-top: 12px;
    font-size: 10pt;
    font-weight: bold;
}
"""

CLOCK_SVG = (
    '<svg class="icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="12" cy="12" r="9.5" stroke="black" stroke-width="1.6"/>'
    '<path d="M12 7v5.5l4 2.3" stroke="black" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
PIN_SVG = (
    '<svg class="icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 21s7-7.1 7-12.1A7 7 0 0 0 5 8.9C5 13.9 12 21 12 21z" '
    'stroke="black" stroke-width="1.6" stroke-linejoin="round"/>'
    '<circle cx="12" cy="8.8" r="2.3" stroke="black" stroke-width="1.6"/></svg>'
)


# ---------------------------------------------------------------------------
# Caps-lock fixing
# ---------------------------------------------------------------------------

def looks_all_caps(s):
    """True if the text looks like it was typed with caps lock on."""
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.8


def fix_caps_sentence(s):
    """Lowercase then capitalize the start of each sentence. Used for descriptions."""
    s = s.lower()
    if s:
        s = s[0].upper() + s[1:]
    s = re.sub(
        r'([.!?]\s+)([a-zà-ÿ])',
        lambda m: m.group(1) + m.group(2).upper(),
        s,
    )
    return s


def fix_caps_title(s):
    """Lowercase then title-case each word, keeping small Italian words lowercase
    (except when they're the first word). Used for titles, places, organizers."""
    s = s.lower()
    words = s.split(" ")
    result = []
    for idx, word in enumerate(words):
        # split into: leading punctuation (quotes, parens...), the core word,
        # an optional apostrophe, and anything after it
        m = re.match(r"^([^a-zà-ÿ]*)([a-zà-ÿ]*)('?)(.*)$", word)
        lead, core, apos, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        should_lower = core in IT_LOWER_WORDS and idx != 0
        if core and not should_lower:
            core = core[0].upper() + core[1:]
        if rest and apos:
            rest = rest[0].upper() + rest[1:]
        result.append(lead + core + apos + rest)
    return " ".join(result)


def normalize_field(value, mode):
    """Apply caps-lock fix only if the field actually looks all-caps."""
    value = (value or "").strip()
    if not looks_all_caps(value):
        return value
    if mode == "title":
        return fix_caps_title(value)
    return fix_caps_sentence(value)


# ---------------------------------------------------------------------------
# CSV field helpers
# ---------------------------------------------------------------------------

def esc(s):
    return html.escape((s or "").strip())


def get_field(row, *names):
    lower_map = {k.lower().strip(): v for k, v in row.items() if k}
    for name in names:
        if name in lower_map:
            return lower_map[name]
    return ""


def parse_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        pass
    try:
        return dateparser.parse(raw, dayfirst=True, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def parse_first_time(raw):
    raw = (raw or "").strip()
    first = raw.split("/")[0].strip() if raw else ""
    for fmt in ("%H:%M", "%H.%M", "%H"):
        try:
            t = datetime.strptime(first, fmt)
            return (t.hour, t.minute)
        except ValueError:
            continue
    return (99, 99)


def format_date_it(d):
    return f"{IT_DAYS[d.weekday()]} {d.day} {IT_MONTHS[d.month]} {d.year}"


# ---------------------------------------------------------------------------
# HTML building
# ---------------------------------------------------------------------------

def build_event_html(row, fix_caps=True):
    title = get_field(row, "title", "titolo", "event", "nome")
    time_raw = get_field(row, "time", "ora", "orario")
    place = get_field(row, "location", "luogo", "place", "venue")
    desc = get_field(row, "description", "descrizione", "desc")
    organizer = get_field(row, "organizer", "organizzatore", "organizzato da")

    if fix_caps:
        title = normalize_field(title, "title")
        place = normalize_field(place, "title")
        desc = normalize_field(desc, "sentence")
        organizer = normalize_field(organizer, "title")

    title, place, desc, organizer = esc(title), esc(place), esc(desc), esc(organizer)

    times = [t.strip() for t in time_raw.split("/") if t.strip()]
    if times:
        time_html = "".join(
            f'<div class="time-line">{CLOCK_SVG}{esc(t)}</div>' for t in times
        )
    else:
        time_html = ""

    place_html = f'{PIN_SVG}{place}' if place else ""
    desc_html = desc.replace("\n", "<br>")
    organizer_html = f'<div class="organizer">{organizer}</div>' if organizer else ""

    return f"""
    <div class="event">
      <div class="event-row">
        <div class="title-cell">{title}</div>
        <div class="time-cell">{time_html}</div>
        <div class="place-cell">{place_html}</div>
      </div>
      <div class="description">{desc_html}</div>
      {organizer_html}
    </div>
    """


def build_full_html(csv_bytes, title_text, logo_data_uris=None, fix_caps=True):
    """csv_bytes: raw bytes of the uploaded CSV. Returns a full HTML document string."""
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    enriched = []
    for row in rows:
        date_raw = get_field(row, "date", "data", "giorno")
        d = parse_date(date_raw)
        t = parse_first_time(get_field(row, "time", "ora", "orario"))
        enriched.append((d, t, row))

    enriched.sort(key=lambda x: (x[0] is None, x[0] or datetime.max.date(), x[1]))

    days = []
    for d, t, row in enriched:
        if days and days[-1][0] == d:
            days[-1][1].append(row)
        else:
            days.append((d, [row]))

    day_blocks_html = []
    for d, day_rows in days:
        heading = format_date_it(d) if d else "Data da definire"
        events_html = "".join(build_event_html(r, fix_caps=fix_caps) for r in day_rows)
        day_blocks_html.append(f"""
        <div class="day-block">
          <div class="day-header">{esc(heading)}</div>
          <div class="day-events">{events_html}</div>
        </div>
        """)

    if logo_data_uris:
      imgs = "".join(f'<img src="{uri}">' for uri in logo_data_uris)
      logo_html = f'<div class="logos">{imgs}</div>'
else:
    logo_html = ""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{CSS}</style>
</head>
<body>
<div class="header">
  {logo_html}
  <h1>{esc(title_text)}</h1>
</div>
{''.join(day_blocks_html)}
</body>
</html>"""
