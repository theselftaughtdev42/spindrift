"""Reading the rendered matrix the way a browser does.

Tests assert on what a user could observe, which for the matrix means: which game a row
is for, which platform a cell is for, and whether that cell is set. This reads all three
out of the ARIA roles and the toggle's `aria-pressed` state — the same contract assistive
technology relies on — so the assertions survive any change to classes, tags, or layout.
"""

from collections import namedtuple
from html.parser import HTMLParser

Cell = namedtuple("Cell", "platform pressed url")


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = {}
        self._game = None
        self._tag = None
        self._depth = 0
        self._text = []
        self._pressed = None
        self._url = None

    def handle_starttag(self, tag, attrs):
        if self._tag is not None:
            if tag == self._tag:
                self._depth += 1
            return

        attrs = dict(attrs)
        if attrs.get("role") == "rowheader":
            self._tag, self._depth, self._text = tag, 1, []
        elif "aria-pressed" in attrs:
            self._tag, self._depth, self._text = tag, 1, []
            self._pressed = attrs["aria-pressed"] == "true"
            self._url = attrs.get("hx-post")

    def handle_data(self, data):
        if self._tag is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if self._tag is None or tag != self._tag:
            return
        self._depth -= 1
        if self._depth:
            return

        text = " ".join("".join(self._text).split())
        if self._pressed is None:
            self._game = text
        else:
            self.cells[(self._game, text)] = Cell(text, self._pressed, self._url)
            self._pressed = None
        self._tag = None


def _read(html):
    reader = _Reader()
    reader.feed(html)
    return reader.cells


def cells(html):
    """Whether each cell in a page is set, keyed by (game name, platform label)."""
    return {key: cell.pressed for key, cell in _read(html).items()}


def toggle_url(html, game, platform):
    """Where that cell posts to — followed rather than guessed, as htmx would."""
    return _read(html)[(game, platform)].url


def only_cell(html):
    """The single cell in a fragment, as a `Cell(platform, pressed, url)`."""
    found = _read(html)
    assert len(found) == 1, f"expected exactly one cell, found {len(found)}"
    return next(iter(found.values()))
