/* After sign-in: ask once whether to turn on notifications on this device (never on the sign-in pages), keep the bell's
   count fresh, and show new notices as phone notifications with our tune while the app is open. */
(function () {
  "use strict";
  var cfgEl = document.getElementById("sb-notify");
  if (!cfgEl || /^\/login/.test(location.pathname)) return;
  var cfg = JSON.parse(cfgEl.textContent), box = document.getElementById("np"), bellN = document.getElementById("bell-n");
  var supported = "Notification" in window && "serviceWorker" in navigator;
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  var csrf = function () { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; };
  var post = function (url, body, json) {
    return fetch(url, { method: "POST", credentials: "same-origin", keepalive: true, headers: json ? { "Content-Type": "application/json", "X-CSRFToken": csrf() } : { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrf() }, body: body });
  };
  var key = function (b64) { var p = "=".repeat((4 - b64.length % 4) % 4), s = atob((b64 + p).replace(/-/g, "+").replace(/_/g, "/")), a = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; };
  var reg = supported ? navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { return null; }) : Promise.resolve(null);

  function subscribe() {  // phone notifications even when the app is closed (needs the server's push keys)
    if (!cfg.vapid) return;
    reg.then(function (r) {
      if (!r || !r.pushManager) return;
      r.pushManager.getSubscription().then(function (s) {
        return s || r.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key(cfg.vapid) });
      }).then(function (s) { if (s) post("/push/subscribe/", JSON.stringify(s), true); }).catch(function () {});
    });
  }

  // 1. Ask once. Not on sign-in pages; not if the browser already has an answer; not after a yes or no on this account or device.
  if (supported && box && Notification.permission === "default" && !cfg.asked && !store.get("sb-notify-asked")) {
    setTimeout(function () { box.hidden = false; document.getElementById("np-yes").focus(); }, 1200);
    document.getElementById("np-yes").addEventListener("click", function () {
      box.hidden = true; store.set("sb-notify-asked", "1");
      Notification.requestPermission().then(function (p) {
        post("/notifications/prompt/", "answer=" + (p === "granted" ? "yes" : "no"));
        if (p === "granted") subscribe();
      });
    });
    document.getElementById("np-no").addEventListener("click", function () {
      box.hidden = true; store.set("sb-notify-asked", "1"); post("/notifications/prompt/", "answer=no");
    });
  } else if (supported && Notification.permission === "granted") {
    subscribe();
  }

  // 2. Keep the bell fresh. Without server push keys, new notices still pop up while the app is open.
  var last = cfg.last || 0, tone = null;
  function check() {
    fetch("/notifications/unread.json?after=" + last, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      if (bellN) { bellN.textContent = d.unread; bellN.hidden = !d.unread; }
      if (d.items && d.items.length) {
        if (document.visibilityState === "visible") { tone = tone || new Audio(cfg.tone); tone.play().catch(function () {}); }
        if (!cfg.vapid && supported && Notification.permission === "granted") {
          reg.then(function (r) { if (!r) return; d.items.forEach(function (it) {
            r.showNotification(it.title, { body: it.text, tag: "sb-" + it.id, icon: cfg.icon, requireInteraction: !!it.critical, data: { url: it.url } });
          }); });
        }
      }
      last = Math.max(last, d.last || 0);
    }).catch(function () {});
  }
  setInterval(check, 60000);
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") check(); });
})();
