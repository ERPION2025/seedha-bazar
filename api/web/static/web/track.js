/* Ad tracking. Nothing loads until the visitor presses Allow. */
(function () {
  var cfg = window.SB_CFG || {}, KEY = "sb_consent", bar = document.getElementById("cc");
  function get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function set(v) { try { localStorage.setItem(KEY, v); } catch (e) {} }
  function load() {
    if (cfg.ga4) {
      var s = document.createElement("script"); s.async = true; s.src = "https://www.googletagmanager.com/gtag/js?id=" + cfg.ga4; document.head.appendChild(s);
      window.dataLayer = window.dataLayer || []; window.gtag = function () { dataLayer.push(arguments); };
      gtag("js", new Date()); gtag("config", cfg.ga4);
    }
    if (cfg.meta) {
      !function (f, b, e, v, n, t, s) { if (f.fbq) return; n = f.fbq = function () { n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments); }; if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = "2.0"; n.queue = []; t = b.createElement(e); t.async = !0; t.src = v; s = b.getElementsByTagName(e)[0]; s.parentNode.insertBefore(t, s); }(window, document, "script", "https://connect.facebook.net/en_US/fbevents.js");
      fbq("init", cfg.meta); fbq("track", "PageView");
    }
  }
  window.sbTrack = function (name) {
    if (get() !== "yes") return;
    if (window.gtag) gtag("event", name);
    if (window.fbq) fbq("trackCustom", name);
  };
  if (get() === "yes") load();
  else if (get() === null && bar) {
    bar.hidden = false;
    document.getElementById("cc-yes").onclick = function () { set("yes"); bar.hidden = true; load(); };
    document.getElementById("cc-no").onclick = function () { set("no"); bar.hidden = true; };
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest("[data-track]"); if (a) window.sbTrack(a.getAttribute("data-track"));
  });
})();
