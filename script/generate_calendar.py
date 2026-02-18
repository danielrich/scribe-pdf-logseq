#!/usr/bin/env python3
"""
generate_calendar.py - Generate a monthly calendar PDF with Google Calendar events.

The PDF uses a fixed grid layout so that Kindle Scribe pen annotations
(stored in .sdr sidecar files) remain aligned when the PDF is regenerated
with updated events.

Usage:
    python3 generate_calendar.py --config CONFIG_PATH [--month YYYY-MM] [--output OUTPUT_PATH]

Dependencies:
    pip3 install reportlab google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

import argparse
import datetime
import calendar
import json
import os
import sys
import pickle

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import Color, black, white, HexColor
from reportlab.pdfgen import canvas

# Page layout constants — these MUST remain identical across regenerations
# so that Scribe pen annotations stay aligned
PAGE_WIDTH, PAGE_HEIGHT = letter  # 612 x 792 points (8.5 x 11 inches)
MARGIN_LEFT = 0.5 * inch
MARGIN_RIGHT = 0.5 * inch
MARGIN_TOP = 0.75 * inch
MARGIN_BOTTOM = 0.5 * inch

HEADER_HEIGHT = 0.6 * inch
DAY_HEADER_HEIGHT = 0.3 * inch

GRID_LEFT = MARGIN_LEFT
GRID_RIGHT = PAGE_WIDTH - MARGIN_RIGHT
GRID_TOP = PAGE_HEIGHT - MARGIN_TOP - HEADER_HEIGHT
GRID_BOTTOM = MARGIN_BOTTOM

GRID_WIDTH = GRID_RIGHT - GRID_LEFT
GRID_HEIGHT = GRID_TOP - GRID_BOTTOM - DAY_HEADER_HEIGHT

COLS = 7  # days of the week
CELL_WIDTH = GRID_WIDTH / COLS

# Colors
COLOR_HEADER_BG = HexColor("#2C3E50")
COLOR_HEADER_TEXT = white
COLOR_DAY_HEADER_BG = HexColor("#ECF0F1")
COLOR_GRID_LINE = HexColor("#BDC3C7")
COLOR_TODAY_BG = HexColor("#EBF5FB")
COLOR_EVENT = HexColor("#2980B9")
COLOR_DAY_NUMBER = HexColor("#2C3E50")
COLOR_OTHER_MONTH = HexColor("#95A5A6")
COLOR_WEEKEND_BG = HexColor("#FAFAFA")

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def get_google_calendar_events(credentials_path, token_path, month_start, month_end):
    """Fetch events from Google Calendar API."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("Google Calendar API libraries not installed.")
        print("Install with: pip3 install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        return []

    SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
    creds = None

    if os.path.exists(token_path):
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                print(f"Google credentials file not found: {credentials_path}")
                print("Download it from Google Cloud Console.")
                print("See README for setup instructions.")
                return []
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    service = build("calendar", "v3", credentials=creds)

    time_min = month_start.isoformat() + "T00:00:00Z"
    time_max = month_end.isoformat() + "T23:59:59Z"

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for event in events_result.get("items", []):
        start = event["start"].get("dateTime", event["start"].get("date"))
        summary = event.get("summary", "(No title)")

        # Parse the date
        if "T" in start:
            event_date = datetime.datetime.fromisoformat(start.replace("Z", "+00:00")).date()
            event_time = datetime.datetime.fromisoformat(start.replace("Z", "+00:00")).strftime("%-I:%M%p").lower()
            display = f"{event_time} {summary}"
        else:
            event_date = datetime.date.fromisoformat(start)
            display = summary

        events.append({"date": event_date, "display": display, "summary": summary})

    return events


def load_events_from_json(json_path, month_start, month_end):
    """Load events from a local JSON file as a fallback/alternative to Google API."""
    if not os.path.exists(json_path):
        return []

    with open(json_path) as f:
        data = json.load(f)

    events = []
    for entry in data:
        event_date = datetime.date.fromisoformat(entry["date"])
        if month_start <= event_date <= month_end:
            display = entry.get("display", entry.get("summary", ""))
            events.append({"date": event_date, "display": display})

    return events


def generate_calendar_pdf(output_path, year, month, events, today=None):
    """Generate a monthly calendar PDF with events in a fixed grid layout."""
    if today is None:
        today = datetime.date.today()

    c = canvas.Canvas(output_path, pagesize=letter)
    c.setTitle(f"Calendar - {calendar.month_name[month]} {year}")

    cal = calendar.Calendar(firstweekday=0)  # Monday start
    month_days = cal.monthdayscalendar(year, month)
    num_weeks = len(month_days)
    cell_height = GRID_HEIGHT / num_weeks

    # --- Month/Year Header ---
    c.setFillColor(COLOR_HEADER_BG)
    header_y = PAGE_HEIGHT - MARGIN_TOP - HEADER_HEIGHT
    c.rect(MARGIN_LEFT, header_y, GRID_WIDTH, HEADER_HEIGHT, fill=1, stroke=0)

    c.setFillColor(COLOR_HEADER_TEXT)
    c.setFont("Helvetica-Bold", 22)
    header_text = f"{calendar.month_name[month]} {year}"
    c.drawCentredString(PAGE_WIDTH / 2, header_y + HEADER_HEIGHT / 2 - 8, header_text)

    # --- Day-of-week headers ---
    day_header_y = GRID_TOP - DAY_HEADER_HEIGHT
    c.setFillColor(COLOR_DAY_HEADER_BG)
    c.rect(GRID_LEFT, day_header_y, GRID_WIDTH, DAY_HEADER_HEIGHT, fill=1, stroke=0)

    c.setFont("Helvetica-Bold", 10)
    for col, day_name in enumerate(DAY_NAMES):
        x = GRID_LEFT + col * CELL_WIDTH
        c.setFillColor(COLOR_DAY_NUMBER)
        c.drawCentredString(x + CELL_WIDTH / 2, day_header_y + 8, day_name)

    # --- Build event lookup by day ---
    events_by_day = {}
    for ev in events:
        day = ev["date"].day
        if ev["date"].month == month and ev["date"].year == year:
            events_by_day.setdefault(day, []).append(ev["display"])

    # --- Draw calendar grid ---
    for week_idx, week in enumerate(month_days):
        for col, day in enumerate(week):
            x = GRID_LEFT + col * CELL_WIDTH
            y = day_header_y - (week_idx + 1) * cell_height

            # Cell background
            is_weekend = col >= 5
            is_today = (day == today.day and month == today.month and year == today.year)

            if is_today:
                c.setFillColor(COLOR_TODAY_BG)
                c.rect(x, y, CELL_WIDTH, cell_height, fill=1, stroke=0)
            elif is_weekend and day != 0:
                c.setFillColor(COLOR_WEEKEND_BG)
                c.rect(x, y, CELL_WIDTH, cell_height, fill=1, stroke=0)

            # Cell border
            c.setStrokeColor(COLOR_GRID_LINE)
            c.setLineWidth(0.5)
            c.rect(x, y, CELL_WIDTH, cell_height, fill=0, stroke=1)

            if day == 0:
                continue

            # Day number
            c.setFont("Helvetica-Bold", 11)
            if is_today:
                # Draw a circle behind today's number
                circle_x = x + 14
                circle_y = y + cell_height - 14
                c.setFillColor(COLOR_EVENT)
                c.circle(circle_x, circle_y, 10, fill=1, stroke=0)
                c.setFillColor(white)
                c.drawCentredString(circle_x, circle_y - 4, str(day))
            else:
                c.setFillColor(COLOR_DAY_NUMBER)
                c.drawString(x + 6, y + cell_height - 16, str(day))

            # Events for this day
            day_events = events_by_day.get(day, [])
            c.setFont("Helvetica", 7)
            c.setFillColor(COLOR_EVENT)

            max_events = int((cell_height - 24) / 10)
            for ev_idx, ev_text in enumerate(day_events[:max_events]):
                ev_y = y + cell_height - 28 - (ev_idx * 10)
                # Truncate long event text to fit cell
                max_chars = int(CELL_WIDTH / 4)
                if len(ev_text) > max_chars:
                    ev_text = ev_text[: max_chars - 1] + "…"
                c.drawString(x + 4, ev_y, ev_text)

            # Show "+N more" if events overflow
            if len(day_events) > max_events:
                overflow_y = y + cell_height - 28 - (max_events * 10)
                c.setFillColor(COLOR_OTHER_MONTH)
                c.setFont("Helvetica-Oblique", 6)
                c.drawString(x + 4, overflow_y, f"+{len(day_events) - max_events} more")

    # --- Footer with generation timestamp ---
    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_OTHER_MONTH)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    c.drawString(MARGIN_LEFT, MARGIN_BOTTOM / 2, f"Generated: {timestamp}")

    c.save()
    print(f"Calendar PDF generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate a monthly calendar PDF with Google Calendar events")
    parser.add_argument("--config", help="Path to config.sh or settings directory")
    parser.add_argument("--month", help="Month to generate (YYYY-MM format). Defaults to current month.")
    parser.add_argument("--output", help="Output PDF path")
    parser.add_argument("--credentials", help="Path to Google OAuth credentials.json")
    parser.add_argument("--events-json", help="Path to a local events JSON file (alternative to Google API)")
    parser.add_argument("--no-google", action="store_true", help="Skip Google Calendar, use local events.json only")
    args = parser.parse_args()

    # Determine month
    if args.month:
        year, month = map(int, args.month.split("-"))
    else:
        today = datetime.date.today()
        year, month = today.year, today.month

    month_start = datetime.date(year, month, 1)
    if month == 12:
        month_end = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        month_end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    # Determine settings directory
    settings_dir = None
    if args.config:
        if os.path.isdir(args.config):
            settings_dir = args.config
        else:
            settings_dir = os.path.dirname(args.config)
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        settings_dir = os.path.join(os.path.dirname(script_dir), "settings")

    # Output path
    if args.output:
        output_path = args.output
    else:
        output_dir = os.path.join(os.path.dirname(settings_dir), "pdf")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"Calendar {year}-{month:02d}.pdf")

    # Collect events
    events = []

    # Try Google Calendar
    if not args.no_google:
        credentials_path = args.credentials or os.path.join(settings_dir, "credentials.json")
        token_path = os.path.join(settings_dir, "google_token.pickle")

        if os.path.exists(credentials_path):
            print(f"Fetching Google Calendar events for {calendar.month_name[month]} {year}...")
            google_events = get_google_calendar_events(credentials_path, token_path, month_start, month_end)
            events.extend(google_events)
            print(f"  Found {len(google_events)} events from Google Calendar")
        else:
            print(f"No Google credentials found at {credentials_path}")
            print("Skipping Google Calendar. See README for setup instructions.")

    # Try local events JSON
    events_json = args.events_json or os.path.join(settings_dir, "events.json")
    if os.path.exists(events_json):
        local_events = load_events_from_json(events_json, month_start, month_end)
        events.extend(local_events)
        print(f"  Found {len(local_events)} events from local events.json")

    print(f"Total events: {len(events)}")

    # Generate the PDF
    generate_calendar_pdf(output_path, year, month, events)
    return output_path


if __name__ == "__main__":
    main()
