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

// Password visibility: wrap every password field and inject a show/hide
// toggle. Done from JS (not in the templates) so the button only exists when
// scripting is available to make it work.
window.addEventListener("DOMContentLoaded", function () {
  var EYE =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><line x1="4" y1="4" x2="20" y2="20"/></svg>';
  var showLabel = document.body.dataset.pwShow || "Show password";
  var hideLabel = document.body.dataset.pwHide || "Hide password";

  document.querySelectorAll('input[type="password"]').forEach(function (input) {
    var wrap = document.createElement("span");
    wrap.className = "pw-field";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "pw-toggle";
    toggle.innerHTML = EYE;
    toggle.setAttribute("aria-label", showLabel);
    toggle.title = showLabel;
    wrap.appendChild(toggle);

    toggle.addEventListener("click", function () {
      var makeVisible = input.type === "password";
      input.type = makeVisible ? "text" : "password";
      toggle.innerHTML = makeVisible ? EYE_OFF : EYE;
      toggle.setAttribute("aria-label", makeVisible ? hideLabel : showLabel);
      toggle.title = makeVisible ? hideLabel : showLabel;
      input.focus();
    });
  });
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
