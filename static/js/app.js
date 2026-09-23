/* Small shared helpers. Server state lives in Django; this file only handles UI glue. */
(function () {
  "use strict";

  // Toasts: any view can set  HX-Trigger: {"toast": {"message": "...", "kind": "good"}}
  function toast(message, kind) {
    var stack = document.getElementById("toastStack");
    if (!stack) return;
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
})();
