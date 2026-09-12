from urllib.parse import urlsplit

# The placeholder a saved search URL has to contain: the spot the game's name is written
# into. Mandatory rather than appended-when-absent, so a mistyped `{nme}` is refused on
# the spot instead of quietly degrading into a URL with a game's name stuck on the end.
SEARCH_PLACEHOLDER = "{}"

# The only schemes a saved URL may use. The value lands in an `href` on every row of the
# catalogue, which is the sharp reason — `javascript:` there would run on a click — but
# the plain one is that a search destination which is not a web address is not a search
# destination.
SEARCH_SCHEMES = ("http", "https")


def search_url_problem(url):
    """What is wrong with a search URL, in words for the cataloguer — or `None` if nothing.

    The one place the shape of a search URL is admitted from. Adding one by hand and
    importing one in a snapshot both ask this, so an imported URL follows exactly the rule a
    typed one does, and the two paths cannot drift apart. Uniqueness is not checked here:
    that lives in the database's index, which neither path can talk its way around.
    """
    if SEARCH_PLACEHOLDER not in url:
        return f"That URL needs {SEARCH_PLACEHOLDER} in it, where the game's name goes."
    if urlsplit(url).scheme not in SEARCH_SCHEMES:
        return "That URL needs to start with http:// or https://."
    return None
