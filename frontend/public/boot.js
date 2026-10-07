// Runs synchronously before first paint. Applies the cached theme and
// language so the page never flashes the wrong colors or direction.
// Keys must match src/lib/preferences.ts.
(function () {
  var root = document.documentElement;
  var theme = null;
  var lang = null;
  try {
    theme = window.localStorage.getItem("hs.theme");
    lang = window.localStorage.getItem("hs.lang");
  } catch {
    // Storage can be unavailable (private mode); fall through to defaults.
  }
  if (theme !== "light" && theme !== "dark" && theme !== "warm") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  if (lang !== "ar" && lang !== "en") lang = "ar";
  root.setAttribute("data-theme", theme);
  root.setAttribute("lang", lang);
  root.setAttribute("dir", lang === "ar" ? "rtl" : "ltr");
})();
