/* Soft in-app alarm for critical weather alerts: Seedha Bazar's own chime, a vibration, up to three rounds.
   Phones only allow sound after the person has touched the page, so if the browser blocks it we play on the first tap.
   Each set of alerts sounds only once per device until it changes. */
(function () {
  "use strict";
  var b = document.getElementById("wx-banner");
  if (!b || !b.getAttribute("data-critical") || !b.getAttribute("data-alarm")) return;
  var key = "sb_alarm_" + b.getAttribute("data-key");
  try { if (localStorage.getItem(key)) return; } catch (e) {}
  var audio = new Audio(b.getAttribute("data-sound")), rounds = 0, stop = document.getElementById("wx-stop");
  audio.volume = 0.8;
  audio.addEventListener("ended", function () { if (++rounds < 3) setTimeout(function () { audio.play().catch(function () {}); }, 1200); else done(); });
  function done() { try { localStorage.setItem(key, "1"); } catch (e) {} if (stop) stop.hidden = true; }
  function start() {
    if (navigator.vibrate) navigator.vibrate([400, 200, 400, 200, 800]);
    return audio.play().then(function () { if (stop) stop.hidden = false; });
  }
  if (stop) stop.addEventListener("click", function () { audio.pause(); rounds = 3; done(); });
  start().catch(function () {
    // Blocked until the first touch: try again then.
    var once = function () { document.removeEventListener("pointerdown", once, true); start().catch(function () {}); };
    document.addEventListener("pointerdown", once, true);
  });
})();
