/* Turn on phone notifications: register the service worker, ask permission, send the subscription to the server. */
(function () {
  "use strict";
  var on = document.getElementById("push-on"), test = document.getElementById("push-test"), out = document.getElementById("push-status");
  if (!on) return;
  var csrf = function () { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; };
  var key = function (b64) { var p = "=".repeat((4 - b64.length % 4) % 4), s = atob((b64 + p).replace(/-/g, "+").replace(/_/g, "/")), a = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; };
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) { on.disabled = true; out.textContent = on.getAttribute("data-no") || "This browser cannot show notifications. Try Chrome."; return; }
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(function (reg) {
    reg.pushManager.getSubscription().then(function (s) { if (s && Notification.permission === "granted") { on.textContent = "✔ " + on.textContent; test.hidden = false; } });
    on.addEventListener("click", function () {
      Notification.requestPermission().then(function (perm) {
        if (perm !== "granted") { out.textContent = "🔕"; return; }
        return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key(on.getAttribute("data-key")) }).then(function (sub) {
          return fetch("/push/subscribe/", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(sub) });
        }).then(function () { out.textContent = "✔"; test.hidden = false; });
      }).catch(function () { out.textContent = "✖"; });
    });
    test.addEventListener("click", function () { fetch("/push/test/", { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf() } }); });
  });
})();
