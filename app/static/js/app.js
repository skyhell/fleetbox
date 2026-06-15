// Progressive enhancement: confirm dialogs without inline handlers, so a strict
// Content-Security-Policy (no 'unsafe-inline' scripts) can be enforced.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (form instanceof HTMLFormElement && form.dataset.confirm) {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  }
});

// Register the service worker so FleetBox is installable and has an offline
// fallback. Same-origin, so it is allowed under our strict CSP.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function () {
      /* offline support is best-effort; ignore registration failures */
    });
  });
}
