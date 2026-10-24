/* Loader: when a page or form takes more than a moment, show a small farming scene that fits where the person is going.
   Nothing shows for fast pages (a short delay first), file downloads, new tabs, or links within the page.
   Pages can also call SBLoader.show("rain") / SBLoader.hide() around their own slow work. */
(function () {
  "use strict";
  var root = document.getElementById("sb-loader");
  if (!root) return;
  var art = root.querySelector(".ld-art"), slow = root.querySelector(".ld-slow"), wait = null, slowWait = null, shown = false;
  var SCENES = [
    [/^\/(weather|kvk\/weather)/, "rain"],
    [/^\/(rates|market|calculator|deals|producers|buyer|enquiry|farmer\/sell|fpo\/sell|farmer\/pools|fpo\/pools|alerts)/, "tarazu"],
    [/^\/(storage|loans)/, "sack"],
    [/^\/(farmer\/groups|fpo\/groups|groups|fpo\/farmers|farmers|orgs|map|fpo\/?$)/, "tractor"],
    [/^\/(farmer\/book|help|issues|advisories|offers|inputs|value)/, "sprout"],
  ];
  function pick(path) {
    for (var i = 0; i < SCENES.length; i++) if (SCENES[i][0].test(path)) return SCENES[i][1];
    return Math.random() < 0.5 ? "wheat" : "sprout";
  }
  function draw(scene) {
    var t = document.getElementById("ld-" + scene) || document.getElementById("ld-wheat");
    art.textContent = "";
    art.appendChild(t.content.cloneNode(true));
  }
  function show(scene, path, delay) {
    if (wait || shown) return;
    wait = setTimeout(function () {
      draw(scene || pick(path || location.pathname));
      root.hidden = false; shown = true;
      requestAnimationFrame(function () { root.classList.add("on"); });
      slowWait = setTimeout(function () { slow.hidden = false; }, 9000);
    }, delay == null ? 350 : delay);
  }
  function hide() {
    clearTimeout(wait); clearTimeout(slowWait); wait = null; shown = false;
    root.classList.remove("on"); root.hidden = true; slow.hidden = true; art.textContent = "";
  }
  function leavesPage(u) {
    if (u.origin !== location.origin) return false;
    if (u.pathname === location.pathname && u.search === location.search) return false;  // same page or a #link
    if (/\.(png|jpe?g|pdf|csv|wav|webmanifest|js|css)$/i.test(u.pathname) || /(^|&)format=/.test(u.search.slice(1))) return false;  // files
    return true;
  }
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || (a.target && a.target !== "_self") || a.hasAttribute("download") || a.hasAttribute("data-no-loader")) return;
    var href = a.getAttribute("href");
    if (!href || href.charAt(0) === "#" || /^(tel|mailto|sms|whatsapp|javascript):/i.test(href)) return;
    var u = new URL(a.href, location.href);
    if (leavesPage(u)) show(null, u.pathname);
  });
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (f.hasAttribute("data-no-loader") || (f.target && f.target !== "_self")) return;
    setTimeout(function () {  // after every other handler: a form a script took over (or a "Cancel" in a confirm) shows nothing
      if (e.defaultPrevented) return;
      var u = new URL(f.getAttribute("action") || location.href, location.href);
      if (!/(^|&)format=/.test(u.search.slice(1))) show(null, u.pathname);
    }, 0);
  });
  window.addEventListener("pageshow", hide);  // also when coming back with the browser's Back button
  root.addEventListener("click", function (e) { if (e.target.closest("[data-ld-close]")) hide(); });
  window.SBLoader = { show: function (scene) { show(scene, null, 0); }, hide: hide };
})();
