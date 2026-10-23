/* Game engine shared by all twelve games: big buttons, read-aloud, voice answers, a timer, points and saving.
   A game registers itself with SBG.register(slug, function (stage, g) { ... }) and calls g.add(points) and g.end(). */
(function () {
  "use strict";
  var cfg = JSON.parse(document.getElementById("game-cfg").textContent);
  var T = function (s, v) { var o = (cfg.t && cfg.t[s]) || s; if (v) for (var k in v) o = o.split("{" + k + "}").join(v[k]); return o; };
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var games = {};
  var usedVoice = false;

  function speak(text) {
    try { if (!window.speechSynthesis) return; speechSynthesis.cancel(); var u = new SpeechSynthesisUtterance(text); u.lang = cfg.speech; u.rate = 0.95; speechSynthesis.speak(u); } catch (e) {}
  }
  var NUMS = { "1": 0, "one": 0, "first": 0, "एक": 0, "पहला": 0, "पहिला": 0, "2": 1, "two": 1, "second": 1, "दो": 1, "दोन": 1, "दूसरा": 1, "दुसरा": 1,
               "3": 2, "three": 2, "third": 2, "तीन": 2, "तीसरा": 2, "तिसरा": 2, "4": 3, "four": 3, "fourth": 3, "चार": 3, "चौथा": 3, "चौथा": 3 };
  function norm(s) { return (s || "").toLowerCase().replace(/[.,!?।]/g, " ").replace(/\s+/g, " ").trim(); }
  /* Listen once. `choices` is a list of lists of words; calls back with the index whose words were heard, or -1. */
  function listen(choices, cb, onText) {
    if (!SR) { cb(-1, ""); return; }
    var r = new SR(); r.lang = cfg.speech; r.interimResults = false; r.maxAlternatives = 5;
    r.onresult = function (e) {
      usedVoice = true;
      var alts = []; for (var i = 0; i < e.results[0].length; i++) alts.push(norm(e.results[0][i].transcript));
      if (onText) onText(alts[0]);
      for (var a = 0; a < alts.length; a++) {
        var words = alts[a].split(" ");
        for (var w = 0; w < words.length; w++) if (NUMS[words[w]] !== undefined && NUMS[words[w]] < choices.length) return cb(NUMS[words[w]], alts[a]);
        for (var c = 0; c < choices.length; c++) for (var k = 0; k < choices[c].length; k++) { var want = norm(choices[c][k]); if (want && alts[a].indexOf(want) >= 0) return cb(c, alts[a]); }
      }
      cb(-1, alts[0]);
    };
    r.onerror = function () { cb(-1, ""); };
    try { r.start(); } catch (e) { cb(-1, ""); }
  }
  function micButton(choices, cb) {
    var b = el("button", "btn ghost mic-big", "🎤 " + T("Say it"));
    if (!SR) { b.hidden = true; return b; }
    b.type = "button";
    b.addEventListener("click", function () {
      b.textContent = "👂 " + T("Listening..."); b.classList.add("live");
      listen(typeof choices === "function" ? choices() : choices, function (i, heard) { b.textContent = "🎤 " + T("Say it"); b.classList.remove("live"); cb(i, heard); });
    });
    return b;
  }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function shuffle(a) { a = a.slice(); for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; } return a; }
  function csrf() { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }

  function run() {
    var root = document.getElementById("game"), hud = document.getElementById("hud"), stage = document.getElementById("stage");
    var score = 0, timers = [];
    var g = {
      T: T, speak: speak, listen: listen, mic: micButton, el: el, shuffle: shuffle, data: cfg.data, lang: cfg.lang,
      add: function (n) { score = Math.max(0, score + n); hud.querySelector(".pts").textContent = score; },
      score: function () { return score; },
      later: function (fn, ms) { var t = setTimeout(fn, ms); timers.push(t); return t; },
      every: function (fn, ms) { var t = setInterval(fn, ms); timers.push(t); return t; },
      flash: function (ok, msg) { var f = el("div", "flash " + (ok ? "ok" : "no"), (ok ? "✔ " : "✖ ") + (msg || (ok ? T("Correct!") : T("Not quite.")))); root.appendChild(f); setTimeout(function () { f.remove(); }, 900); if (msg) speak(msg); },
      end: function (lesson) {
        timers.forEach(function (t) { clearTimeout(t); clearInterval(t); }); timers = [];
        stage.innerHTML = "";
        var box = el("div", "card tint end");
        box.appendChild(el("h2", null, T("Game over")));
        box.appendChild(el("div", "big", score + " " + T("Points")));
        if (lesson) box.appendChild(el("p", null, lesson));
        var saved = el("p", "mute"); box.appendChild(saved);
        var again = el("button", "btn", "↻ " + T("Play again")); again.type = "button"; again.addEventListener("click", start); box.appendChild(again);
        var back = el("a", "btn ghost", T("Games")); back.href = "/games/"; box.appendChild(back);
        stage.appendChild(box);
        speak(T("Your score") + " " + score);
        if (!cfg.signed_in) { saved.textContent = T("Sign in to save your points."); return; }
        fetch("/games/" + cfg.slug + "/score/", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({ score: score, voice: usedVoice }) }).then(function (r) { return r.json(); }).then(function (d) { if (d.points != null) saved.textContent = T("Saved to your points.") + " +" + d.points; }).catch(function () {});
      }
    };
    function start() {
      timers.forEach(function (t) { clearTimeout(t); clearInterval(t); }); timers = []; score = 0; usedVoice = false;
      hud.querySelector(".pts").textContent = "0"; stage.innerHTML = "";
      games[cfg.slug](stage, g);
    }
    var go = document.getElementById("go");
    go.addEventListener("click", function () { go.hidden = true; start(); });
  }
  window.SBG = { register: function (slug, fn) { games[slug] = fn; } };
  document.addEventListener("DOMContentLoaded", run);
})();
