/* The same map on Google Maps (MAP_PROVIDER=google with GOOGLE_MAPS_API_KEY). District boundaries, centres, FPOs and
   problems, the nearest-KVK button, and directions. Google calls window.sbGoogleMap once its script has loaded. */
window.sbGoogleMap = function () {
  "use strict";
  var el = document.getElementById("map"); if (!el) return;
  var T = JSON.parse(document.getElementById("map-text").textContent);
  var mode = el.getAttribute("data-mode"), stateFile = el.getAttribute("data-state-file"), state = el.getAttribute("data-state");
  var focus = JSON.parse(el.getAttribute("data-focus") || "[]").map(function (s) { return s.toLowerCase(); });
  var map = new google.maps.Map(el, { center: { lat: 22.5, lng: 79 }, zoom: 5, mapTypeControl: false, streetViewControl: false });
  var info = new google.maps.InfoWindow(), stats = {};
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var dir = function (lat, lon) { return '<a href="https://www.google.com/maps/dir/?api=1&destination=' + lat + "," + lon + '" target="_blank" rel="noopener">' + esc(T.directions) + " ↗</a>"; };
  function dot(lat, lon, color, html) {
    var m = new google.maps.Marker({ position: { lat: lat, lng: lon }, map: map, icon: { path: google.maps.SymbolPath.CIRCLE, scale: 8, fillColor: color, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 2 } });
    m.addListener("click", function () { info.setContent(html); info.open({ map: map, anchor: m }); });
    return m;
  }
  function bounds() {
    if (!stateFile) return Promise.resolve();
    return fetch(el.getAttribute("data-geo-base") + stateFile).then(function (r) { return r.json(); }).then(function (gj) {
      map.data.addGeoJson(gj);
      var max = 1; Object.keys(stats).forEach(function (k) { max = Math.max(max, stats[k].farmers || 0); });
      map.data.setStyle(function (f) {
        var name = f.getProperty("district"), mine = focus.indexOf(name.toLowerCase()) >= 0, s = stats[name];
        return { strokeColor: mine ? "#14532d" : "#78716c", strokeWeight: mine ? 3 : 1, fillColor: mine ? "#1f7a3f" : "#a8a29e", fillOpacity: s ? 0.15 + 0.55 * (s.farmers || 0) / max : (mine ? 0.18 : 0.03) };
      });
      map.data.addListener("click", function (e) {
        var name = e.feature.getProperty("district"), s = stats[name], html = "<b>" + esc(name) + "</b>";
        if (s) html += "<br>" + esc(T.farmers) + ": " + s.farmers + "<br>" + esc(T.fpos) + ": " + s.fpos + "<br>" + esc(T.issues) + ": " + s.issues;
        info.setContent(html); info.setPosition(e.latLng); info.open(map);
      });
      var b = new google.maps.LatLngBounds(), any = false;
      map.data.forEach(function (f) { if (!focus.length || focus.indexOf(f.getProperty("district").toLowerCase()) >= 0) { any = true; f.getGeometry().forEachLatLng(function (ll) { b.extend(ll); }); } });
      if (!any) map.data.forEach(function (f) { f.getGeometry().forEachLatLng(function (ll) { b.extend(ll); }); });
      map.fitBounds(b);
    });
  }
  if (mode === "kvk") {
    fetch("/map/data/", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      stats = d.districts || {};
      bounds().then(function () {
        if (d.centre && d.centre.lat) dot(d.centre.lat, d.centre.lon, "#1e3a8a", "<b>🏛️ " + esc(d.centre.name) + "</b>");
        (d.fpos || []).forEach(function (o) { dot(o.lat, o.lon, "#f59e0b", "<b>🏢 " + esc(o.name) + '</b><br><a href="' + o.url + '">' + esc(T.open) + "</a> · " + dir(o.lat, o.lon)); });
        (d.issues || []).forEach(function (i) { dot(i.lat, i.lon, "#b91c1c", "<b>⚠️ " + esc(i.label) + '</b><br><a href="' + i.url + '">' + esc(T.open) + "</a>"); });
      });
    });
    return;
  }
  bounds().then(function () { return fetch("/map/data/?state=" + encodeURIComponent(state)).then(function (r) { return r.json(); }); }).then(function (d) {
    if (!(d.centres || []).length && !(d.orgs || []).length) { var n = document.getElementById("map-empty"); if (n) n.hidden = false; return fetch("/map/data/").then(function (r) { return r.json(); }); }
    return d;
  }).then(function (d) {
    var centres = d.centres || [];
    centres.forEach(function (c) { c.m = dot(c.lat, c.lon, "#14532d", "<b>🏛️ " + esc(c.name) + "</b><br>" + esc(c.kind) + "<br>" + dir(c.lat, c.lon)); });
    (d.orgs || []).forEach(function (o) { dot(o.lat, o.lon, "#f59e0b", "<b>🏢 " + esc(o.name) + "</b><br>" + dir(o.lat, o.lon)); });
    var btn = document.getElementById("near-me"), out = document.getElementById("near-out");
    if (btn) btn.addEventListener("click", function () {
      out.textContent = T.finding;
      navigator.geolocation.getCurrentPosition(function (p) {
        var me = { lat: p.coords.latitude, lng: p.coords.longitude };
        new google.maps.Marker({ position: me, map: map, title: T.you });
        var best = null;
        centres.forEach(function (c) { c.km = google.maps.geometry ? 0 : Math.hypot(c.lat - me.lat, c.lon - me.lng) * 111; if (!best || c.km < best.km) best = c; });
        if (!best) { out.textContent = T.none; map.setCenter(me); map.setZoom(10); return; }
        out.innerHTML = esc(T.nearest) + ": <b>" + esc(best.name) + "</b> · ~" + best.km.toFixed(0) + " km · " + dir(best.lat, best.lon);
        var b = new google.maps.LatLngBounds(); b.extend(me); b.extend({ lat: best.lat, lng: best.lon }); map.fitBounds(b);
      }, function () { out.textContent = T.blocked; });
    });
  });
};
