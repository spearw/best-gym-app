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

  // ---------------------------------------------------------------- session player

  // Sets that haven't reached the server yet. Leaving the page warns while any are
  // pending; they retry with backoff and as soon as the phone is back online.
  var unsavedSets = new Set();
  window.addEventListener("beforeunload", function (e) {
    if (unsavedSets.size) { e.preventDefault(); e.returnValue = ""; }
  });
  window.addEventListener("online", function () {
    unsavedSets.forEach(function (row) { if (row.state === "error") row.save(); });
  });

  function csrfToken() {
    try { return JSON.parse(document.body.getAttribute("hx-headers"))["X-CSRFToken"]; }
    catch (err) { return ""; }
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

    // The template editor: which session the library rail adds to, and the rail drawer.
    // A saved session has only one session, so it's always selected.
    window.Alpine.data("templateEditor", function (first, single) {
      return {
        session: single ? first : null,
        library: false,
        pick: function (id) {
          this.session = id;
          var search = document.getElementById("railSearch");
          if (search) search.focus({ preventScroll: true });
        },
      };
    });

    // A form-video upload in the player: sign, PUT straight to the bucket (with progress),
    // then confirm, which redraws the card. The file never passes through Django.
    window.Alpine.data("formVideo", function () {
      return {
        busy: false, pct: 0,
        upload: function (e) {
          var file = e.target.files && e.target.files[0];
          e.target.value = "";
          if (!file) return;
          var d = this.$root.dataset, self = this;  // $el would be the file input
          if (file.size > Number(d.max) * 1024 * 1024) { toast("That video is over " + d.max + " MB — trim it to a minute or two.", "err"); return; }
          var type = file.type && file.type.indexOf("video/") === 0 ? file.type : "video/mp4";
          var body = new FormData();
          body.append("se", d.se); body.append("size", file.size); body.append("content_type", type);
          this.busy = true; this.pct = 0;
          fetch(d.startUrl, { method: "POST", body: body, credentials: "same-origin", headers: { "X-CSRFToken": csrfToken() } })
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
            .then(function (res) {
              if (!res.ok) throw new Error(res.body.error || "Couldn't start the upload");
              return new Promise(function (resolve, reject) {
                var xhr = new XMLHttpRequest();
                xhr.open("PUT", res.body.url);
                xhr.setRequestHeader("Content-Type", type);
                xhr.upload.onprogress = function (ev) { if (ev.lengthComputable) self.pct = Math.round(ev.loaded / ev.total * 100); };
                xhr.onload = function () { xhr.status < 300 ? resolve(res.body) : reject(new Error("The upload failed — try again")); };
                xhr.onerror = function () { reject(new Error("The upload failed — check your connection")); };
                xhr.send(file);
              });
            })
            .then(function (started) {
              return window.htmx.ajax("POST", started.done_url, { target: "#videos-" + d.se, swap: "outerHTML" });
            })
            .catch(function (err) { self.busy = false; toast(err.message, "err"); });
        },
      };
    });

    // One set row in the session player. Each tick or change saves that set; saves for
    // one row run one at a time, so the last change always wins.
    window.Alpine.data("setRow", function () {
      return {
        load: "", reps: "", time: "", rir: "", done: false,
        state: "saved", note: "", busy: false, again: false, attempt: 0, timer: null,
        init: function () {
          var d = this.$el.dataset;
          this.url = d.url; this.number = d.number; this.timeUnit = d.timeUnit || "s";
          this.load = d.load || ""; this.reps = d.reps || ""; this.time = d.time || "";
          this.rir = d.rir || ""; this.done = d.done === "true";
        },
        tick: function () { this.done = !this.done; this.save(); },
        save: function () {
          if (this.busy) { this.again = true; return; }
          clearTimeout(this.timer);
          this.busy = true; this.state = "saving"; unsavedSets.add(this);
          var body = new FormData();
          body.append("load", this.load); body.append("reps", this.reps);
          body.append("time", this.time); body.append("time_unit", this.timeUnit);
          body.append("rir", this.rir);
          if (this.done) body.append("done", "on");
          var self = this;
          fetch(this.url, { method: "POST", body: body, credentials: "same-origin", headers: { "X-CSRFToken": csrfToken() } })
            .then(function (r) {
              // A save that ends on another page (e.g. the sign-in page) did not save.
              if (r.redirected) return { ok: false, status: 401, body: { error: "you've been signed out — sign in and enter it again" } };
              return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
            })
            .then(function (res) {
              self.busy = false;
              if (self.again) { self.again = false; self.save(); return; }
              if (res.ok) {
                self.attempt = 0; self.state = "saved"; self.note = ""; unsavedSets.delete(self);
              } else if (res.status >= 500) {
                self.retry();
              } else {
                // The server refused these numbers (or the session is closed): don't retry.
                self.state = "invalid"; unsavedSets.delete(self);
                self.note = (res.body && res.body.error) || "Not saved";
                toast("Set " + self.number + ": " + self.note, "err");
              }
            })
            .catch(function () { self.busy = false; if (self.again) { self.again = false; self.save(); } else { self.retry(); } });
        },
        retry: function () {
          this.state = "error"; this.attempt += 1;
          this.note = "Not saved yet — retrying";
          if (this.attempt === 1) toast("Couldn't save set " + this.number + " — retrying", "err");
          var self = this;
          this.timer = setTimeout(function () { self.save(); }, Math.min(30000, 1000 * Math.pow(2, this.attempt)));
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
    document.querySelectorAll(".droptarget").forEach(function (c) { c.classList.remove("droptarget"); });
  }
  function markDropTarget(evt) {
    clearDropTargets();
    var col = evt.to && evt.to.closest(".day-col, .tpl-sess");
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
    return { session: to.dataset.session || "", day: to.dataset.day || "", index: positionIn(item) };
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
            source: evt.item, target: list.dataset.target || "#programEditor", swap: "outerHTML", values: dropValues(evt.to, evt.item),
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
            source: source, target: lib.dataset.target || "#programEditor", swap: "outerHTML", values: values,
          });
        },
      });
    });
  }

  // Ctrl+Z / Cmd+Z on the program board presses Undo. Not while typing in a field, except
  // the library search: picking a day puts the cursor there, so it's usually where the
  // coach is right after adding an exercise.
  document.addEventListener("keydown", function (e) {
    if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.key.toLowerCase() !== "z") return;
    if (e.target.closest("input, textarea, select, [contenteditable]") && e.target.id !== "railSearch") return;
    var button = document.querySelector("#programEditor [data-undo]");
    if (!button) return;
    e.preventDefault();
    button.click();  // with nothing to undo, the server answers with a toast saying why
  });

  // Keyboard users open the history line with Enter or Space, like a button.
  document.addEventListener("keydown", function (e) {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("[data-hist]")) {
      e.preventDefault();
      e.target.click();
    }
  });

  // Library rail: tapping an athlete's history line opens their full log for that exercise.
  document.addEventListener("click", function (e) {
    var pop = document.getElementById("histPop");
    if (!pop) return;
    var line = e.target.closest("[data-hist]");
    if (!line) {
      if (!e.target.closest("#histPop")) pop.classList.remove("open");
      return;
    }
    e.stopPropagation();
    pop.innerHTML = line.querySelector("template").innerHTML;
    var r = line.getBoundingClientRect();
    pop.style.left = Math.max(10, r.left - 310) + "px";
    pop.style.top = Math.max(10, Math.min(window.innerHeight - 240, r.top - 20)) + "px";
    pop.classList.add("open");
  });

  // Boosted navigation in the coach shell swaps only #coach-main, so the browser never
  // resets the scroll position: a new page would open as far down as the old one was.
  // Start each new page at the top. (Actions within a page aren't boosted, so they keep
  // their place; the back button restores its own scroll position.) This listens before
  // the swap: afterwards the clicked link and the old main area are detached, so their
  // events never reach the document.
  // HTMX's own scrollIntoViewOnBoost would then line up #coach-main's edge (74px down)
  // after settling, so it's turned off in favour of this.
  // A link with a #target (e.g. an alert pointing at one session's issue) lands on that
  // element instead: it's scrolled into view, a collapsed session around it is opened,
  // and it flashes briefly.
  function goToTarget(hash) {
    var el = hash && hash.length > 1 ? document.getElementById(decodeURIComponent(hash.slice(1))) : null;
    if (!el) return false;
    var details = el.closest("details");
    if (details) details.open = true;
    el.scrollIntoView({ block: "center" });
    el.classList.remove("is-target");
    void el.offsetWidth;  // restart the highlight animation
    el.classList.add("is-target");
    return true;
  }
  document.addEventListener("htmx:beforeSwap", function (e) {
    if (e.detail.boosted && e.detail.target && e.detail.target.id === "coach-main") {
      var elt = e.detail.requestConfig && e.detail.requestConfig.elt;
      var hash = elt && elt.href ? new URL(elt.href, window.location.href).hash : "";
      var anchor = e.detail.pathInfo && e.detail.pathInfo.anchor;
      if (!hash && anchor) hash = "#" + anchor;
      // After HTMX has swapped and settled (it scrolls to an anchor itself, to the top edge),
      // so the target ends up centred rather than under the sticky header.
      setTimeout(function () { if (!goToTarget(hash)) window.scrollTo(0, 0); }, 60);
    }
  });

  // ---------------------------------------------------------------- installing the app (PWA)

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () { /* the site works without it */ });
    });
  }

  // The "Install the app" card on the athlete's Home: Chrome/Android offers a real install
  // button (beforeinstallprompt); iPhone Safari gets the Share → Add to Home Screen steps.
  // Hidden once installed (standalone) or dismissed.
  var installEvent = null;
  function installState() {
    var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
    var dismissed = storage("installDismissed", "") === "1";
    var ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
    return { show: !standalone && !dismissed && (installEvent || ios), ios: ios && !installEvent };
  }
  function renderInstall(root) {
    var card = (root || document).querySelector ? (root || document).querySelector("#installCard") : null;
    if (!card) return;
    var st = installState();
    card.hidden = !st.show;
    card.querySelector("[data-ios]").hidden = !st.ios;
    card.querySelector("[data-install]").hidden = st.ios;
  }
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    installEvent = e;
    renderInstall(document);
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-install]") && installEvent) {
      installEvent.prompt();
      installEvent.userChoice.finally(function () { installEvent = null; renderInstall(document); });
    }
    if (e.target.closest("[data-install-dismiss]")) {
      store("installDismissed", "1");
      renderInstall(document);
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    renderInstall(document);
    if (window.htmx) window.htmx.config.scrollIntoViewOnBoost = false;
    goToTarget(window.location.hash);
    showInitialToasts(document);
    onReady(document);
    initSortables(document);
  });
  document.addEventListener("htmx:load", function (e) {
    renderInstall(e.target);
    showInitialToasts(e.target);
    onReady(e.target);
    initSortables(e.target);
  });
})();
