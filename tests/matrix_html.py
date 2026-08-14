"""Reading the rendered matrix the way a browser does.

Tests assert on what a user could observe, which for the matrix means: which game a row
is for, which platform a cell is for, and whether that cell is set. This reads all three
out of the ARIA roles and the toggle's `aria-pressed` state — the same contract assistive
technology relies on — so the assertions survive any change to classes, tags, or layout.

The add form is read the same way: through the field names and values a browser would
submit, and through its position among the grid's rows.
"""

from collections import namedtuple
from html.parser import HTMLParser

Cell = namedtuple("Cell", "platform pressed url")
AddForm = namedtuple("AddForm", "action name platforms checked focused")
Deletion = namedtuple("Deletion", "url confirm")


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


def set_platforms(html, game):
    """Which platforms are set for one game, read off the rendered grid."""
    return {platform for (row, platform), is_set in cells(html).items() if row == game and is_set}


def toggle_url(html, game, platform):
    """Where that cell posts to — followed rather than guessed, as htmx would."""
    return _read(html)[(game, platform)].url


def only_cell(html):
    """The single cell in a fragment, as a `Cell(platform, pressed, url)`."""
    found = _read(html)
    assert len(found) == 1, f"expected exactly one cell, found {len(found)}"
    return next(iter(found.values()))


class _FormReader(HTMLParser):
    """The add form's controls, read as the fields a browser would submit."""

    def __init__(self):
        super().__init__()
        self.action = None
        self.name = None
        self.platforms = []
        self.checked = set()
        self.focused = False
        self._in_form = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self._in_form = True
            self.action = attrs.get("hx-post") or attrs.get("action")
        elif self._in_form and tag == "input":
            if attrs.get("name") == "name":
                self.name = attrs.get("value", "")
                self.focused = "autofocus" in attrs
            elif attrs.get("name") == "platform":
                self.platforms.append(attrs["value"])
                if "checked" in attrs:
                    self.checked.add(attrs["value"])

    def handle_endtag(self, tag):
        if tag == "form":
            self._in_form = False


def add_form(html):
    """The add form as it would submit: `AddForm(action, name, platforms, checked)`.

    `platforms` is every platform offered, in the order they appear; `checked` is the
    subset that would be sent. `focused` is whether the name field asks for focus.
    """
    reader = _FormReader()
    reader.feed(html)
    return AddForm(
        reader.action, reader.name, reader.platforms, reader.checked, reader.focused
    )


class _RowReader(HTMLParser):
    """Grid rows in document order, whatever element each happens to be built from."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._tag = None
        self._depth = 0
        self._label = None
        self._header = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self._tag is None:
            if attrs.get("role") == "row":
                self._tag, self._depth, self._label = tag, 1, None
            return

        if tag == self._tag:
            self._depth += 1
        # The row carrying the name field is the entry row; any other row is named by
        # its rowheader. Neither depends on which element the row is made of.
        if attrs.get("name") == "name":
            self._label = "add"
        elif attrs.get("role") == "rowheader" and self._header is None:
            self._header, self._text = tag, []

    def handle_data(self, data):
        if self._header is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if self._header is not None and tag == self._header:
            self._label = " ".join("".join(self._text).split())
            self._header = None
            return
        if self._tag is None or tag != self._tag:
            return
        self._depth -= 1
        if self._depth:
            return
        self.rows.append(self._label)
        self._tag = None


def rows(html):
    """The grid's rows top to bottom: `"add"` for the entry form, else the game name.

    The header row has no rowheader and no name field, so it reads as `None`.
    """
    reader = _RowReader()
    reader.feed(html)
    return [row for row in reader.rows if row is not None]


class _DeleteReader(HTMLParser):
    """Each row's delete control: where it sends, and what it asks before sending."""

    def __init__(self):
        super().__init__()
        self.controls = {}
        self._game = None
        self._header = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self._header is None and attrs.get("role") == "rowheader":
            self._header, self._text = tag, []
        elif "hx-delete" in attrs:
            self.controls[self._game] = Deletion(
                attrs["hx-delete"], attrs.get("hx-confirm")
            )

    def handle_data(self, data):
        if self._header is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if self._header is not None and tag == self._header:
            self._game = " ".join("".join(self._text).split())
            self._header = None


def deletion(html, game):
    """That game's delete control as `Deletion(url, confirm)`.

    `confirm` is the question the cataloguer is asked first, or `None` if the control
    would delete without asking.
    """
    reader = _DeleteReader()
    reader.feed(html)
    return reader.controls[game]
