// An expired session is answered by the proxy in front, not by Spindrift: it replies to the
// request with a redirect to the sign-in. htmx follows that inside the XHR, so what comes
// back is a sign-in page where a fragment was asked for, and swapping it would put somebody
// else's HTML into a table row. A reply from any origin but this one means the session went,
// and only a whole navigation can get it back — the proxy bounces that one properly.
document.body.addEventListener("htmx:beforeSwap", function (event) {
  const repliedFrom = event.detail.xhr.responseURL;
  if (repliedFrom && new URL(repliedFrom, location.href).origin !== location.origin) {
    event.detail.shouldSwap = false;
    location.reload();
  }
});
