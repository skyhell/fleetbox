// Progressive enhancements. Everything here is optional comfort — the app is
// fully usable without JavaScript — and CSP-clean (no inline handlers).

// --- Confirm dialogs ---------------------------------------------------------
// Forms marked data-confirm get a styled <dialog> instead of window.confirm.
(function () {
  var dialog = null;

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.className = "confirm-dialog";
    var message = document.createElement("p");
    var actions = document.createElement("div");
    actions.className = "form-actions";
    var ok = document.createElement("button");
    ok.type = "button";
    ok.className = "btn btn-danger";
    ok.textContent = document.body.dataset.confirmOk || "OK";
    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn";
    cancel.textContent = document.body.dataset.confirmCancel || "Cancel";
    actions.appendChild(ok);
    actions.appendChild(cancel);
    dialog.appendChild(message);
    dialog.appendChild(actions);
    document.body.appendChild(dialog);

    ok.addEventListener("click", function () {
      var form = dialog._form;
      dialog.close();
      if (form) form.submit(); // bypasses the submit listener below
    });
    cancel.addEventListener("click", function () {
      dialog.close();
    });
    return dialog;
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.dataset.confirm) return;
    if (typeof HTMLDialogElement === "undefined") {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
      return;
    }
    event.preventDefault();
    var d = ensureDialog();
    d.querySelector("p").textContent = form.dataset.confirm;
    d._form = form;
    d.showModal();
  });
})();

// --- One-time DOM enhancements ------------------------------------------------
window.addEventListener("DOMContentLoaded", function () {
  var body = document.body;

  // Password visibility: wrap every password field and inject a show/hide
  // toggle. Done from JS so the button only exists when it can work.
  var EYE =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><line x1="4" y1="4" x2="20" y2="20"/></svg>';
  var showLabel = body.dataset.pwShow || "Show password";
  var hideLabel = body.dataset.pwHide || "Hide password";

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

  // Mobile keyboards: number fields open the numeric pad. Fields that allow
  // fractions get the decimal variant.
  document.querySelectorAll('input[type="number"]').forEach(function (input) {
    if (!input.hasAttribute("inputmode")) {
      var step = input.getAttribute("step") || "";
      input.setAttribute("inputmode", step.indexOf(".") >= 0 ? "decimal" : "numeric");
    }
  });

  // Date quick-pick: "today" / "yesterday" buttons next to entry-date fields.
  function localISO(offsetDays) {
    var d = new Date();
    d.setDate(d.getDate() + offsetDays);
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  var dateLabels = [
    [body.dataset.dateToday || "Today", 0],
    [body.dataset.dateYesterday || "Yesterday", -1],
  ];
  document
    .querySelectorAll(
      'input[type="date"][name="performed_on"], input[type="date"][name="filled_on"], ' +
        'input[type="date"][name="spent_on"]'
    )
    .forEach(function (input) {
      var holder = document.createElement("span");
      holder.className = "date-quick";
      dateLabels.forEach(function (pair) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = pair[0];
        btn.addEventListener("click", function () {
          input.value = localISO(pair[1]);
          input.dispatchEvent(new Event("change", { bubbles: true }));
        });
        holder.appendChild(btn);
      });
      input.insertAdjacentElement("afterend", holder);
    });

  // Print buttons: elements marked .js-print open the browser print dialog.
  document.querySelectorAll(".js-print").forEach(function (btn) {
    btn.addEventListener("click", function () {
      window.print();
    });
  });

  // Tables marked data-enhance become sortable (click a header), get a text
  // filter when they hold more than five rows, and collapse long lists to a
  // page of PAGE rows with a "show more" button.
  var PAGE = 20;
  document.querySelectorAll("table[data-enhance]").forEach(function (table) {
    var tbody = table.tBodies[0];
    if (!tbody || !table.tHead) return;

    var query = "";
    var shown = PAGE;
    var moreBtn = null;

    function cellValue(row, index) {
      var cell = row.cells[index];
      return cell ? cell.textContent.trim() : "";
    }
    function asNumber(text) {
      // Accept "1.234,56", "1,234.56" and plain numbers; NaN otherwise.
      var normalized = text.replace(/[^0-9,.\-]/g, "");
      if (!normalized) return NaN;
      if (normalized.lastIndexOf(",") > normalized.lastIndexOf(".")) {
        normalized = normalized.replace(/\./g, "").replace(",", ".");
      } else {
        normalized = normalized.replace(/,/g, "");
      }
      return parseFloat(normalized);
    }

    // Show matching rows only; when no filter is active, cap at `shown` (paging).
    // A filter searches across every row, so it temporarily overrides paging.
    function refresh() {
      var rows = Array.prototype.slice.call(tbody.rows);
      var visible = 0;
      rows.forEach(function (row) {
        var matches = query === "" || row.textContent.toLowerCase().indexOf(query) >= 0;
        var show = matches && (query !== "" || visible < shown);
        row.hidden = !show;
        if (show) visible++;
      });
      if (moreBtn) {
        // Inline display beats the .btn class rule (a plain [hidden] attribute
        // would be overridden by it), so the button truly disappears.
        moreBtn.style.display = query === "" && shown < rows.length ? "" : "none";
      }
    }

    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, index) {
      if (!th.textContent.trim()) return; // action columns stay unsortable
      th.classList.add("sortable");
      th.addEventListener("click", function () {
        var ascending = !th.classList.contains("sort-asc");
        Array.prototype.forEach.call(table.tHead.rows[0].cells, function (other) {
          other.classList.remove("sort-asc", "sort-desc");
        });
        th.classList.add(ascending ? "sort-asc" : "sort-desc");

        var rows = Array.prototype.slice.call(tbody.rows);
        rows.sort(function (a, b) {
          var va = cellValue(a, index);
          var vb = cellValue(b, index);
          var na = asNumber(va);
          var nb = asNumber(vb);
          var result;
          if (!isNaN(na) && !isNaN(nb)) {
            result = na - nb;
          } else {
            result = va.localeCompare(vb, document.documentElement.lang);
          }
          return ascending ? result : -result;
        });
        rows.forEach(function (row) { tbody.appendChild(row); });
        refresh();
      });
    });

    if (tbody.rows.length > 5) {
      var filter = document.createElement("input");
      filter.type = "search";
      filter.className = "table-filter";
      filter.placeholder = body.dataset.tableFilter || "Filter…";
      filter.setAttribute("aria-label", filter.placeholder);
      filter.addEventListener("input", function () {
        query = filter.value.trim().toLowerCase();
        refresh();
      });
      table.parentNode.insertBefore(filter, table);
    }

    if (tbody.rows.length > PAGE) {
      moreBtn = document.createElement("button");
      moreBtn.type = "button";
      moreBtn.className = "btn btn-sm show-more";
      moreBtn.textContent = body.dataset.tableMore || "Show more";
      moreBtn.addEventListener("click", function () {
        shown += PAGE;
        refresh();
      });
      table.parentNode.insertBefore(moreBtn, table.nextSibling);
    }

    refresh();
  });
});

// --- Keyboard shortcuts --------------------------------------------------------
// "/" focuses the search box; on a vehicle page "n" opens the service quick-add
// and "t" the fuel quick-add.
document.addEventListener("keydown", function (event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  var target = event.target;
  if (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  ) {
    return;
  }
  if (event.key === "/") {
    var search = document.querySelector(".topsearch input");
    if (search) {
      event.preventDefault();
      search.focus();
    }
  } else if (event.key === "n" || event.key === "t") {
    var link = document.getElementById(event.key === "n" ? "quick-service" : "quick-fuel");
    if (link) {
      event.preventDefault();
      link.click();
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
