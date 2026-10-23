/* Maps with free, open data: OpenStreetMap tiles and district boundaries (geoBoundaries, ODbL, from LGD).
   <div id="map" data-mode="public|kvk" data-state-file="madhya-pradesh.json" data-state="Madhya Pradesh" data-focus='["Rewa"]'> */
(function () {
  "use strict";
  var el = document.getElementById("map");
  if (!el || !window.L) return;
  var T = JSON.parse(document.getElementById("map-text").textContent);
  var mode = el.getAttribute("data-mode"), stateFile = el.getAttribute("data-state-file"), state = el.getAttribute("data-state");
  var focus = JSON.parse(el.getAttribute("data-focus") || "[]").map(function (s) { return s.toLowerCase(); });
  var map = L.map(el, { zoomControl: true, attributionControl: true }).setView([22.5, 79], 5);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · ' + T.boundaries }).addTo(map);
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var dir = function (lat, lon) { return '<a href="https://www.google.com/maps/dir/?api=1&destination=' + lat + "," + lon + '" target="_blank" rel="noopener noreferrer">' + esc(T.directions) + " ↗</a>"; };
  var layer = null, stats = {};

  function drawBoundaries() {
    if (!stateFile) return Promise.resolve();
    return fetch(el.getAttribute("data-geo-base") + stateFile).then(function (r) { return r.json(); }).then(function (gj) {
      var max = 1; Object.keys(stats).forEach(function (k) { max = Math.max(max, stats[k].farmers || 0); });
      layer = L.geoJSON(gj, {
        style: function (f) {
          var name = f.properties.district, mine = focus.indexOf(name.toLowerCase()) >= 0, s = stats[name];
          var fill = s ? 0.15 + 0.55 * (s.farmers || 0) / max : (mine ? 0.18 : 0.03);
          return { color: mine ? "#14532d" : "#78716c", weight: mine ? 3 : 1, fillColor: mine ? "#1f7a3f" : "#a8a29e", fillOpacity: fill };
        },
        onEachFeature: function (f, lyr) {
          var name = f.properties.district, s = stats[name];
          var html = "<b>" + esc(name) + "</b>";
          if (s) html += "<br>" + esc(T.farmers) + ": " + s.farmers + "<br>" + esc(T.fpos) + ": " + s.fpos + " · " + esc(T.ngos) + ": " + s.ngos +
            "<br>" + esc(T.stock) + ": " + Math.round(s.stock_q) + " q<br>" + esc(T.issues) + ": " + s.issues + "<br>" + esc(T.listings) + ": " + s.listings;
          lyr.bindPopup(html);
        }
      }).addTo(map);
      var focused = [];
      layer.eachLayer(function (l) { if (focus.indexOf(l.feature.properties.district.toLowerCase()) >= 0) focused.push(l); });
      map.fitBounds((focused.length ? L.featureGroup(focused) : layer).getBounds(), { padding: [10, 10] });
    }).catch(function () {});
  }

  function dot(lat, lon, color, html) {
    return L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 }).bindPopup(html).addTo(map);
  }

  if (mode === "kvk") {
    fetch("/kvk/map/data/", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      stats = d.districts || {};
      return drawBoundaries().then(function () {
        if (d.centre && d.centre.lat) dot(d.centre.lat, d.centre.lon, "#14532d", "<b>🏛️ " + esc(d.centre.name) + "</b>");
        (d.fpos || []).forEach(function (o) { dot(o.lat, o.lon, "#f59e0b", "<b>🏢 " + esc(o.name) + "</b><br>" + esc(o.district) + '<br><a href="' + o.url + '">' + esc(T.open) + "</a> · " + dir(o.lat, o.lon)); });
        (d.issues || []).forEach(function (i) { dot(i.lat, i.lon, i.urgent ? "#b91c1c" : "#ef4444", "<b>⚠️ " + esc(i.label) + '</b><br><a href="' + i.url + '">' + esc(T.open) + "</a> · " + dir(i.lat, i.lon)); });
      });
    });
  } else {
    drawBoundaries().then(function () {
      return fetch("/map/data/?state=" + encodeURIComponent(state)).then(function (r) { return r.json(); });
    }).then(function (d) {
      if (!d) return;
      var centres = d.centres || [];
      centres.forEach(function (c) { c.m = dot(c.lat, c.lon, "#14532d", "<b>🏛️ " + esc(c.name) + "</b><br>" + esc(c.kind) + (c.phone ? '<br>📞 <a href="tel:' + esc(c.phone) + '">' + esc(c.phone) + "</a>" : "") + (c.address ? "<br>" + esc(c.address) : "") + "<br>" + dir(c.lat, c.lon)); });
      (d.orgs || []).forEach(function (o) { dot(o.lat, o.lon, "#f59e0b", "<b>🏢 " + esc(o.name) + "</b><br>" + esc(o.kind) + " · " + esc(o.district) + "<br>" + dir(o.lat, o.lon)); });
      var btn = document.getElementById("near-me"), out = document.getElementById("near-out");
      if (btn) btn.addEventListener("click", function () {
        if (!navigator.geolocation) return;
        out.textContent = T.finding;
        navigator.geolocation.getCurrentPosition(function (p) {
          var me = [p.coords.latitude, p.coords.longitude];
          L.circleMarker(me, { radius: 7, color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 1 }).addTo(map).bindPopup(esc(T.you));
          if (!centres.length) { out.textContent = T.none; map.setView(me, 10); return; }
          var R = 6371, rad = Math.PI / 180, best = null;
          centres.forEach(function (c) {
            var dLat = (c.lat - me[0]) * rad, dLon = (c.lon - me[1]) * rad;
            var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(me[0] * rad) * Math.cos(c.lat * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
            c.km = 2 * R * Math.asin(Math.sqrt(a));
            if (!best || c.km < best.km) best = c;
          });
          out.innerHTML = esc(T.nearest) + ": <b>" + esc(best.name) + "</b> · " + best.km.toFixed(1) + " km · " + dir(best.lat, best.lon);
          map.fitBounds(L.latLngBounds([me, [best.lat, best.lon]]), { padding: [40, 40] });
          best.m.openPopup();
        }, function () { out.textContent = T.blocked; }, { enableHighAccuracy: true, timeout: 15000 });
      });
    });
  }
})();
