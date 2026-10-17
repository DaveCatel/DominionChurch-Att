"""The printable attendance register for one service session (a PDF).

Layout: the church name and the words "Attendance register", the service name, its date and
start / end time, then a table of everyone who attended (name, phone, department, clock in and
clock out), alphabetical, with page numbers. Plain built-in fonts: names with French accents
print correctly, characters outside Western European text are replaced with "?".
"""
import io
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#1b1d2b")
MUTED = colors.HexColor("#6b6f85")
HEAD = colors.HexColor("#2d3050")
STRIPE = colors.HexColor("#f3f4f9")
LINE = colors.HexColor("#d9dbe6")


@dataclass
class PdfRow:
    name: str
    phone: str | None
    departments: str  # already joined, e.g. "Choir, Ushers"
    clock_in: datetime | None
    clock_out: datetime | None


def _plain(text) -> str:
    """Safe for the built-in fonts (anything they cannot draw becomes "?")."""
    return (text or "").encode("cp1252", "replace").decode("cp1252")


def _t(text) -> str:
    """Safe for the built-in fonts and for PDF paragraph markup."""
    return escape(_plain(text))


def _sort_key(name: str) -> str:
    """Alphabetical the way people expect: ignore capitals and accents, so \u00c9tienne sorts under E."""
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name or "") if not unicodedata.combining(c))
    return stripped.casefold()


class _NumberedCanvas(canvas.Canvas):
    """Adds "Page 2 of 5" and the footer to every page once the total is known."""

    footer_text = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(MUTED)
            self.drawString(15 * mm, 10 * mm, self.footer_text)
            self.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def build_attendance_pdf(
    church_name: str,
    service_name: str,
    service_date: date,
    start: datetime,
    end: datetime | None,
    rows: list[PdfRow],
    tz: tzinfo,
    generated_at: datetime,
) -> bytes:
    hhmm = lambda d: d.astimezone(tz).strftime("%H:%M") if d else "\u2014"
    times = f"{hhmm(start)} \u2013 {hhmm(end)}" if end else f"from {hhmm(start)}"
    rows = sorted(rows, key=lambda r: _sort_key(r.name))

    styles = {
        "church": ParagraphStyle("church", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=INK, alignment=TA_CENTER),
        "kind": ParagraphStyle("kind", fontName="Helvetica", fontSize=11, leading=14, textColor=MUTED, alignment=TA_CENTER, spaceAfter=10),
        "service": ParagraphStyle("service", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=INK, alignment=TA_CENTER),
        "when": ParagraphStyle("when", fontName="Helvetica", fontSize=11, leading=15, textColor=INK, alignment=TA_CENTER),
        "summary": ParagraphStyle("summary", fontName="Helvetica", fontSize=9.5, leading=13, textColor=MUTED, alignment=TA_CENTER, spaceBefore=6),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=11, textColor=INK),
        "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.white),
        "empty": ParagraphStyle("empty", fontName="Helvetica-Oblique", fontSize=11, leading=15, textColor=MUTED, alignment=TA_CENTER, spaceBefore=18),
    }

    story = [
        Paragraph(_t(church_name), styles["church"]),
        Paragraph("Attendance register", styles["kind"]),
        Paragraph(_t(service_name), styles["service"]),
        Paragraph(f"{service_date:%A, %d %B %Y} &nbsp;&middot;&nbsp; {times}", styles["when"]),
    ]
    left = sum(1 for r in rows if r.clock_out)
    story.append(
        Paragraph(f"Present: <b>{len(rows)}</b> &nbsp;&middot;&nbsp; Clocked out: <b>{left}</b>", styles["summary"])
    )
    story.append(Spacer(1, 8 * mm))

    if not rows:
        story.append(Paragraph("No one attended this session.", styles["empty"]))
    else:
        header = [Paragraph(h, styles["head"]) for h in ("#", "Name", "Phone", "Department", "Clock in", "Clock out")]
        data = [header]
        for i, r in enumerate(rows, 1):
            data.append(
                [
                    Paragraph(str(i), styles["cell"]),
                    Paragraph(_t(r.name), styles["cell"]),
                    Paragraph(_t(r.phone) or "\u2014", styles["cell"]),
                    Paragraph(_t(r.departments) or "\u2014", styles["cell"]),
                    Paragraph(hhmm(r.clock_in), styles["cell"]),
                    Paragraph(hhmm(r.clock_out), styles["cell"]),
                ]
            )
        widths = [9 * mm, 52 * mm, 34 * mm, 45 * mm, 20 * mm, 20 * mm]
        table = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), HEAD),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ]
        for row in range(2, len(data), 2):
            style.append(("BACKGROUND", (0, row), (-1, row), STRIPE))
        table.setStyle(TableStyle(style))
        story.append(table)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
        title=f"Attendance - {service_name} - {service_date.isoformat()}",
        author=church_name,
    )

    class Canvas(_NumberedCanvas):
        footer_text = f"{_plain(church_name)}  \u00b7  generated {generated_at.astimezone(tz):%d %b %Y %H:%M}"

    doc.build(story, canvasmaker=Canvas)
    return buffer.getvalue()
