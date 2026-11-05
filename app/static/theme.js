// Applies the saved light/dark preference before first paint.
// Loaded synchronously in <head>; the page CSP forbids inline scripts.
(function () {
  "use strict";
  try {
    var value = localStorage.getItem("video-workspace-theme");
    if (value === "light" || value === "dark") document.documentElement.dataset.theme = value;
  } catch (_) {
    /* storage unavailable: follow the system setting */
  }
})();
