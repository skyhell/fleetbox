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
