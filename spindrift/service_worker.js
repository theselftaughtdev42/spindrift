// Here only so browsers will offer to install Spindrift. It caches nothing and answers no
// requests: every page still comes from the server, so the catalogue is always current and
// the proxy in front still sees every request.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
