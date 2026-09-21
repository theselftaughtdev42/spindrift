"""Who a request is from, as the proxy in front says — never as the request itself claims.

Spindrift authenticates nobody. A proxy does that (Authentik's outpost, oauth2-proxy) and
passes its verdict along in headers. Those headers are worth exactly as much as the hop
they arrived over: anything that can reach the app directly can set them itself and be
whoever it likes. So they are read only where a deployment has said a proxy is there, and
a `ProxyAuth` is that statement. Without one the headers are not read at all, and a
deployment on a home network goes on having no identity and no sign-in, as it always has.
"""

import os
from dataclasses import dataclass

from werkzeug.datastructures import Headers

# What Authentik's proxy outpost sends. The uid is the account's own id, which survives a
# rename; the rest are labels, and a person can change any of them this afternoon.
UID_HEADER = "X-authentik-uid"

# In preference order, because a deployment may map only some of them through.
NAME_HEADERS = ("X-authentik-name", "X-authentik-username", "X-authentik-email")

# Truthy spellings of `SPINDRIFT_PROXY_AUTH`. Anything else, including nothing, is off: a
# deployment has to say a proxy is there, because assuming one is how headers get believed
# that nobody checked.
ENABLED = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class Cataloguer:
    """The person a request is from.

    `uid` is what identifies them and the only thing worth storing; `name` exists to be
    shown and logged, and may be different tomorrow.
    """

    uid: str
    name: str


@dataclass(frozen=True)
class ProxyAuth:
    """A deployment's statement that an authenticating proxy stands in front of the app.

    Its existence is the whole permission to read the identity headers. `hub_url` is where
    the proxy's own application hub lives, if the deployment says — the way back out to
    whatever else sits behind the same sign-in.
    """

    hub_url: str | None = None


def resolve_proxy_auth() -> ProxyAuth | None:
    """What the environment says about the proxy, or `None` where it says nothing."""
    if os.environ.get("SPINDRIFT_PROXY_AUTH", "").strip().lower() not in ENABLED:
        return None
    return ProxyAuth(hub_url=os.environ.get("SPINDRIFT_AUTH_HUB", "").strip() or None)


def identify(headers: Headers) -> Cataloguer | None:
    """Who the proxy says this is, or `None` where the request never passed through one.

    A uid and nothing else is still somebody: the uid stands in as the name rather than
    the page showing a blank where a person should be.
    """
    uid = headers.get(UID_HEADER, "").strip()
    if not uid:
        return None
    for header in NAME_HEADERS:
        name = headers.get(header, "").strip()
        if name:
            return Cataloguer(uid=uid, name=name)
    return Cataloguer(uid=uid, name=uid)
