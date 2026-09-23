/* Small shared helpers. Server state lives in Django; this file only handles UI glue. */
(function () {
  "use strict";

  // Toasts: any view can set  HX-Trigger: {"toast": {"message": "...", "kind": "good"}}
  // Django messages on a full page load arrive as #initialToasts JSON.
  function toast(message, kind) {
    var stack = document.getElementById("toastStack");
    if (!stack || !message) return;
    var t = document.createElement("div");
    t.className = "toast" + (kind ? " " + kind : "");
    t.textContent = message;
    stack.appendChild(t);
    setTimeout(function () {
      t.classList.add("out");
      setTimeout(function () { t.remove(); }, 240);
    }, 3400);
  }
  window.toast = toast;

  document.addEventListener("toast", function (e) {
    var d = e.detail || {};
    toast(d.message || d.value || "", d.kind);
  });

  // Modals are HTMX partials swapped into #modal; closing just empties it.
  function closeModal() {
    var m = document.getElementById("modal");
    if (m) m.innerHTML = "";
  }
  window.closeModal = closeModal;
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeModal();
  });
  document.addEventListener("closeModal", closeModal);

  // Copy-to-clipboard buttons: <button data-copy="#inputId">.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy]");
    if (!btn) return;
    var input = document.querySelector(btn.getAttribute("data-copy"));
    if (!input) return;
    var done = function () { toast("Link copied", "good"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(input.value).then(done);
    } else {
      input.select(); document.execCommand("copy"); done();
    }
  });

  function onReady(root) {
    // Tell the server the browser's time zone on sign-up and join forms.
    var tz = "";
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (err) { tz = ""; }
    (root || document).querySelectorAll('input[name="browser_timezone"]').forEach(function (i) {
      if (!i.value) i.value = tz;
    });
  }

  // Django messages ride along as <script id="initialToasts"> in full pages and in
  // boosted partial swaps alike; show them once and remove the script.
  function showInitialToasts(root) {
    var el = (root || document).querySelector ? (root || document).querySelector("#initialToasts") : null;
    if (!el && root && root.id === "initialToasts") el = root;
    if (!el) return;
    try { JSON.parse(el.textContent).forEach(function (t) { toast(t.message, t.kind); }); }
    catch (err) { /* ignore malformed */ }
    el.remove();
  }

  // ---------------------------------------------------------------- program editor

  function storage(key, fallback) {
    try { return window.localStorage.getItem(key) || fallback; } catch (err) { return fallback; }
  }
  function store(key, value) {
    try { window.localStorage.setItem(key, value); } catch (err) { /* private mode etc. */ }
  }

  document.addEventListener("alpine:init", function () {
    // The selected day and the columns/list choice live outside #programEditor, so they
    // survive every redraw of the board. The view choice is remembered per browser.
    window.Alpine.data("programEditor", function () {
      return {
        day: null,
        library: false,  // the library drawer on narrow screens
        view: storage("boardView", "cols"),
        setView: function (v) { this.view = v; store("boardView", v); },
        pick: function (dayId) {
          this.day = dayId;
          var search = document.getElementById("railSearch");
          if (search) search.focus({ preventScroll: true });
        },
      };
    });

    // The prescription modal: custom fields and optional per-set rows.
    // Per-set rows follow the main Reps and Load fields until the coach edits a row.
    window.Alpine.data("rxForm", function (fields, rows, parent, sets, vary, basis) {
      return {
        fields: fields, rows: rows, sets: sets, vary: vary, basis: basis,
        repScheme: parent.reps, load: parent.load,
        addField: function () { if (this.fields.length < 8) this.fields.push({ key: "", value: "" }); },
        removeField: function (i) { this.fields.splice(i, 1); },
        syncRows: function () {
          var n = Math.max(1, Math.min(20, parseInt(this.sets, 10) || 1));
          while (this.rows.length < n) this.rows.push({ reps: this.repScheme, load: this.load, edited: false });
          while (this.rows.length > n) this.rows.pop();
          var self = this;
          this.rows.forEach(function (row) {
            if (!row.edited) { row.reps = self.repScheme; row.load = self.load; }
          });
        },
      };
    });
  });

  // Drag and drop on the board. Every session list (each filling its day column) is a
  // Sortable in the "rx" group; the library list is a clone-only source in the same group.
  // The day being dropped on gets the mockup's .droptarget outline. Dropping posts the
  // new position and the server redraws the editor.
  function clearDropTargets() {
    document.querySelectorAll(".day-col.droptarget").forEach(function (c) { c.classList.remove("droptarget"); });
  }
  function markDropTarget(evt) {
    clearDropTargets();
    var col = evt.to && evt.to.closest(".day-col");
    if (col) col.classList.add("droptarget");
    return true;
  }
  function positionIn(item) {
    // Count the exercise cards above the dropped element (it may itself be a library card).
    var i = 0;
    for (var n = item.previousElementSibling; n; n = n.previousElementSibling) {
      if (n.classList.contains("rx-item")) i++;
    }
    return i;
  }
  function dropValues(to, item) {
    return { session: to.dataset.session || "", day: to.dataset.day, index: positionIn(item) };
  }

  function initSortables(root) {
    if (!window.Sortable) return;
    var scope = root || document;
    var lists = Array.prototype.slice.call(scope.querySelectorAll("[data-rx-list]"));
    if (scope.matches && scope.matches("[data-rx-list]")) lists.push(scope);
    lists.forEach(function (list) {
      if (list._sortable) return;
      list._sortable = window.Sortable.create(list, {
        group: "rx", animation: 120, draggable: ".rx-item", ghostClass: "is-dragging",
        onMove: markDropTarget,
        onEnd: function (evt) {
          clearDropTargets();
          if (evt.from === evt.to && evt.oldIndex === evt.newIndex) return;
          window.htmx.ajax("POST", evt.item.dataset.moveUrl, {
            source: evt.item, target: "#programEditor", swap: "outerHTML", values: dropValues(evt.to, evt.item),
          });
        },
      });
    });

    var libs = Array.prototype.slice.call(scope.querySelectorAll("[data-lib-list]"));
    if (scope.matches && scope.matches("[data-lib-list]")) libs.push(scope);
    libs.forEach(function (lib) {
      if (lib._sortable) return;
      lib._sortable = window.Sortable.create(lib, {
        group: { name: "rx", pull: "clone", put: false }, sort: false, draggable: ".lib-item",
        filter: ".addbtn", preventOnFilter: false, ghostClass: "is-dragging",
        onMove: markDropTarget,
        onEnd: function (evt) {
          clearDropTargets();
          if (evt.to === evt.from) return;
          var values = dropValues(evt.to, evt.item);
          values.exercise = evt.item.dataset.exercise;
          var source = evt.to;
          evt.item.remove();  // the server redraws the day with the real exercise card
          window.htmx.ajax("POST", lib.dataset.addUrl, {
            source: source, target: "#programEditor", swap: "outerHTML", values: values,
          });
        },
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    showInitialToasts(document);
    onReady(document);
    initSortables(document);
  });
  document.addEventListener("htmx:load", function (e) {
    showInitialToasts(e.target);
    onReady(e.target);
    initSortables(e.target);
  });
})();
