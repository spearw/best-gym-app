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

  document.addEventListener("DOMContentLoaded", function () {
    showInitialToasts(document);
    onReady(document);
  });
  document.addEventListener("htmx:load", function (e) {
    showInitialToasts(e.target);
    onReady(e.target);
  });
})();
