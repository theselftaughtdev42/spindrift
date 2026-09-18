from urllib.parse import urlsplit

# The spot a game's name is written into. Mandatory rather than appended when absent, so a
# mistyped `{nme}` is refused instead of quietly becoming a URL with a name on the end.
SEARCH_PLACEHOLDER = "{}"

# The value lands in an `href` on every row of the catalogue, where `javascript:` would run
# on a click.
SEARCH_SCHEMES = ("http", "https")


def search_url_problem(url):
    """What is wrong with a search URL, in words for the cataloguer — or `None` if nothing.

    The one place the shape of a search URL is admitted from: a typed one and an imported
    one both ask this, so the two cannot drift. Uniqueness is the database's index instead.
    """
    if SEARCH_PLACEHOLDER not in url:
        return f"That URL needs {SEARCH_PLACEHOLDER} in it, where the game's name goes."
    if urlsplit(url).scheme not in SEARCH_SCHEMES:
        return "That URL needs to start with http:// or https://."
    return None
