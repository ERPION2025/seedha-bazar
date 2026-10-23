/* Where is the visitor? Asks the browser once the person taps, resolves it to a district on the server, or lets them pick by hand. */
(function () {
  var bar = document.getElementById("locbar");
  if (!bar) return;
  var $ = function (id) { return document.getElementById(id); };
  var listeners = [];
  if (bar.dataset.reload === "1") listeners.push(function () { location.reload(); });
  var KEY = "sb_loc_asked";

  function csrf() { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  function post(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); }).catch(function () { return { ok: false, error: "unavailable" }; });
  }
  function say(text) { var m = $("loc-msg"); m.textContent = text || ""; m.hidden = !text; }
  function applied(res) {
    $("loc-text").textContent = res.label || bar.dataset.tNone;
    bar.dataset.has = "1"; say("");
    listeners.forEach(function (fn) { fn(res); });
  }

  function ask() {
    if (!navigator.geolocation) { say(bar.dataset.tFail); openSheet(); return; }
    say(bar.dataset.tFinding);
    try { localStorage.setItem(KEY, "1"); } catch (e) {}
    navigator.geolocation.getCurrentPosition(function (p) {
      post("/location/resolve/", { lat: p.coords.latitude, lon: p.coords.longitude }).then(function (res) {
        if (res.ok) applied(res); else { say(bar.dataset.tFail); openSheet(); }
      });
    }, function (err) {
      say(err && err.code === 1 ? bar.dataset.tDenied : bar.dataset.tFail); openSheet();
    }, { timeout: 15000, maximumAge: 600000 });
  }

  var places = null;
  function fill(sel, items, keep) {
    sel.innerHTML = "";
    items.forEach(function (v) { var o = document.createElement("option"); o.value = v; o.textContent = v; sel.appendChild(o); });
    if (keep && items.indexOf(keep) >= 0) sel.value = keep;
  }
  function openSheet() {
    var go = function () {
      fill($("loc-state"), Object.keys(places));
      $("loc-state").onchange = function () { fill($("loc-district"), places[$("loc-state").value] || []); };
      $("loc-state").onchange();
      $("loc-sheet").hidden = false;
    };
    if (places) go(); else fetch("/rates/places/").then(function (r) { return r.json(); }).then(function (d) { places = d.places || {}; go(); });
  }
  $("loc-pick").onclick = openSheet;
  $("loc-cancel").onclick = function () { $("loc-sheet").hidden = true; };
  $("loc-save").onclick = function () {
    post("/location/choose/", { state: $("loc-state").value, district: $("loc-district").value }).then(function (res) {
      if (res.ok) { $("loc-sheet").hidden = true; applied(res); }
    });
  };
  $("loc-gps").onclick = ask;

  // Already allowed on this device earlier: no need to ask again.
  if (bar.dataset.auto === "1" && !bar.dataset.has && navigator.permissions && navigator.permissions.query) {
    navigator.permissions.query({ name: "geolocation" }).then(function (s) { if (s.state === "granted") ask(); }).catch(function () {});
  }
  window.SBLoc = { onChange: function (fn) { listeners.push(fn); }, ask: ask, choose: openSheet };
})();
