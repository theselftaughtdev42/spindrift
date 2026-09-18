from urllib.parse import urlsplit

# Mandatory rather than appended when absent, so a mistyped placeholder is refused.
SEARCH_PLACEHOLDER = "{}"

# The value lands in an `href` on every row, where `javascript:` would run on a click.
SEARCH_SCHEMES = ("http", "https")


def search_url_problem(url):
    """What is wrong with a search URL, in words for the cataloguer — or `None` if nothing.

    The one place a URL's shape is admitted from, so a typed one and an imported one agree.
    """
    if SEARCH_PLACEHOLDER not in url:
        return f"That URL needs {SEARCH_PLACEHOLDER} in it, where the game's name goes."
    if urlsplit(url).scheme not in SEARCH_SCHEMES:
        return "That URL needs to start with http:// or https://."
    return None
