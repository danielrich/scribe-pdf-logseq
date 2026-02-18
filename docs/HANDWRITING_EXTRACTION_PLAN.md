# Handwriting-to-Calendar Implementation Plan

## Overview

Read handwritten events from the Kindle Scribe calendar PDF and push them to Google Calendar. Fully automatic — plug in the Scribe and it works.

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `script/read_calendar.sh` | Shell wrapper, called by `scribe_watcher.sh` |
| `script/read_calendar.py` | Core logic: render, crop, detect, recognize, push |

### Modified Files

| File | Change |
|------|--------|
| `script/scribe_watcher.sh` | Add `read_calendar.sh` call after `sync_calendar.sh` |
| `script/scribe_watcher.ps1` | Same for Windows |
| `script/setup.sh` | Add config prompts for handwriting extraction |
| `script/setup.ps1` | Same for Windows |
| `requirements.txt` | Add `pymupdf`, `Pillow`, `anthropic` |

---

## Implementation: read_calendar.py

### Step 1: Find calendar PDFs on the Kindle

```python
def find_calendar_pdfs(kindle_mount: str, pdf_name_pattern: str) -> list[Path]:
    """
    Scan kindle_mount/documents/ for files matching the calendar naming
    convention (e.g., "Calendar 2025-03.pdf").

    Returns list of paths to calendar PDFs on the device.
    """
```

We look in `{kindle_mount}/documents/` for files matching the configured `CALENDAR_PDF_NAME` pattern. This is the same location `sync_calendar.sh` copies PDFs to.

### Step 2: Render PDF pages as images

```python
def render_page(pdf_path: Path, page_num: int = 0, dpi: int = 200) -> Image:
    """
    Render a PDF page to a PIL Image using pymupdf.

    The rendered image includes both the printed calendar content
    AND any pen annotation overlays from the Scribe.

    Args:
        pdf_path: Path to the calendar PDF on the Kindle
        page_num: Page index (calendars are single-page)
        dpi: Resolution. 200 is enough for handwriting recognition
             without being excessively large.
    """
```

Key decision: we render the **Kindle's copy** of the PDF (the one with `.sdr` annotation overlays), not our locally generated clean copy. pymupdf can render PDF pages that include annotation layers.

**Open question**: Does pymupdf render Kindle `.sdr` overlay data, or only standard PDF annotations? If `.sdr` data isn't embedded in the PDF itself, we may need to:
1. Check if Scribe writes annotations directly into the PDF (some firmware versions do)
2. If not, overlay the `.sdr` pen data ourselves (parse enough of the binary format to extract stroke coordinates and render them with Pillow)
3. Alternative: use the Scribe's "export with annotations" if available

**Testing needed on device**: Connect the Scribe, write on a calendar, and check whether the PDF file itself is modified or if all annotations live exclusively in `.sdr`.

### Step 3: Crop day cells from the grid

```python
# Grid constants — must match generate_calendar.py exactly
PAGE_WIDTH, PAGE_HEIGHT = 612, 792  # letter size in points
MARGIN_LEFT = 36       # 0.5 * 72
MARGIN_RIGHT = 36
MARGIN_TOP = 54        # 0.75 * 72
MARGIN_BOTTOM = 36
HEADER_HEIGHT = 43.2   # 0.6 * 72
DAY_HEADER_HEIGHT = 21.6  # 0.3 * 72
COLS = 7

def get_cell_bounds(year: int, month: int) -> dict[int, tuple[int, int, int, int]]:
    """
    Calculate pixel bounding boxes for each day cell.

    Returns dict mapping day number -> (x1, y1, x2, y2) in image coordinates.
    Accounts for DPI scaling between PDF points and rendered pixels.

    The grid layout is deterministic given the month (number of weeks
    determines row height), so we can compute this without parsing the PDF.
    """
```

The grid coordinates come directly from `generate_calendar.py`'s constants. We import them or duplicate them (with a shared constants module if we want to be clean about it). The number of weeks in the month determines `cell_height`, and then each cell's position is:

```
x = GRID_LEFT + col * CELL_WIDTH
y = GRID_TOP - DAY_HEADER_HEIGHT - (week_idx + 1) * cell_height
```

Scaled by `dpi / 72` to convert from PDF points to image pixels.

### Step 4: Detect cells with handwriting

```python
def has_handwriting(cell_image: Image, clean_cell_image: Image, threshold: float = 0.02) -> bool:
    """
    Compare the Kindle's rendered cell against a clean render of the
    locally generated PDF (no annotations).

    If the pixel difference exceeds the threshold, there's handwriting.

    This approach:
    - Handles cells that already have printed event text (we diff against
      the clean version, so printed text cancels out)
    - Works regardless of what the handwriting looks like
    - Simple and fast
    """
```

We render BOTH:
1. The Kindle's PDF (with annotations)
2. Our local clean PDF (without annotations)

Then diff each cell. Any significant difference = handwriting. This is better than trying to detect "ink" generically because cells may have printed event text.

### Step 5: Send to Claude vision API

```python
def recognize_handwriting(cell_image: Image, day: int, month: int, year: int,
                          existing_events: list[str]) -> dict | None:
    """
    Send a cell image to Claude's vision API for handwriting recognition.

    Returns structured event data:
    {
        "summary": "Dentist appointment",
        "time": "14:00",         # 24h format, or null for all-day
        "end_time": "15:00",     # optional
        "confidence": 0.92
    }

    Or None if the handwriting is not a calendar event.

    The prompt includes:
    - The date context (so Claude knows what day this cell represents)
    - Any existing Google Calendar events for that day (so Claude can
      distinguish between handwritten additions and annotations of
      existing events)
    """
```

Prompt design is critical. Something like:

```
This image is a cropped cell from a calendar for {weekday}, {month} {day}, {year}.
The cell may contain handwritten text added with a pen on a Kindle Scribe.

Existing typed events already on this day: {existing_events}

If there is handwritten text that represents a NEW calendar event (not just
annotations/marks on existing events), extract it as:
- summary: the event description
- time: start time in HH:MM 24h format (or null if all-day)
- end_time: end time if specified (or null)
- confidence: your confidence from 0.0 to 1.0

If the handwriting is not a new event (just doodles, checkmarks, underlines
on existing events, etc.), return null.

Respond in JSON only.
```

### Step 6: Push to Google Calendar

```python
def create_calendar_event(service, year: int, month: int, day: int,
                          event_data: dict) -> str:
    """
    Create a Google Calendar event via the API.

    Uses the EXISTING credentials/token from calendar sync setup.
    Requires calendar.events scope (read-write) — if the current token
    only has calendar.readonly, we'll need to re-authorize.

    Returns the created event ID.
    """
```

The current calendar sync uses `calendar.readonly` scope. We'll need `calendar.events` for write access. The setup script should handle the scope upgrade — delete the existing token and re-authorize.

### Step 7: Deduplication and history tracking

```python
HISTORY_FILE = "settings/calendar_read_history.json"

# Structure:
# {
#     "2025-03-15": [
#         {
#             "summary": "Dentist appointment",
#             "time": "14:00",
#             "google_event_id": "abc123",
#             "extracted_at": "2025-03-14T22:30:00"
#         }
#     ]
# }
```

Before creating an event, check:
1. Does Google Calendar already have a similar event on that day? (fuzzy match on summary)
2. Have we already extracted this entry in a previous sync? (check history file)

---

## Open Questions (to test on the laptop with Scribe)

### Q1: Does the Scribe embed annotations in the PDF or only in .sdr?

**Test**: Write on a calendar PDF on the Scribe. Connect via USB. Open the PDF from the Kindle `documents/` folder in a desktop PDF viewer (Preview, Chrome, etc.).

- **If annotations are visible**: pymupdf will render them directly. Simplest path.
- **If annotations are NOT visible**: They're in `.sdr` only. We'll need to either:
  - Parse the `.sdr` binary format (fragile but doable)
  - Render the `.sdr` strokes ourselves with Pillow onto the page image
  - Investigate if `pymupdf` can load `.sdr` as an annotation layer

### Q2: What's the .sdr directory structure for a calendar PDF?

**Test**: After writing on a calendar, check:
```bash
ls -la "/Volumes/Kindle/documents/Calendar 2025-03.sdr/"
file "/Volumes/Kindle/documents/Calendar 2025-03.sdr/"*
xxd "/Volumes/Kindle/documents/Calendar 2025-03.sdr/"* | head -100
```

Document the filenames, sizes, and first few hundred bytes of each file.

### Q3: Scope upgrade — does deleting the token and re-authorizing work cleanly?

**Test**: Delete `settings/google_token.pickle`, change scope to `calendar.events`, run `generate_calendar.py`. Should trigger re-auth flow.

### Q4: Claude vision accuracy on Scribe handwriting

**Test**: Manually crop a few cells with handwriting, send to the API, check accuracy. This determines whether the approach is viable before building the full pipeline.

---

## Execution Order

1. **On laptop with Scribe**: Answer Q1 and Q2 above (10 min)
2. **Build `read_calendar.py`**: Core pipeline (render → crop → diff → API → push)
3. **Build `read_calendar.sh`**: Shell wrapper with config
4. **Wire into watcher**: Add to `scribe_watcher.sh` / `.ps1`
5. **Update setup scripts**: Add config prompts
6. **Test end-to-end**: Write on calendar, plug in, verify events appear in Google Calendar
