// Registers the service worker that makes Spindrift installable. Its address comes from the
// page, which knows where the app is mounted.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register(document.currentScript.dataset.serviceWorker);
}
