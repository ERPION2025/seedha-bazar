/* Read-aloud helper, the same on every screen. A tab on the right edge opens a small panel:
   "Read this screen" speaks the page, "What should I do here?" speaks the actions available.
   Uses the phone's own text-to-speech (Web Speech API), so it needs no server and no data.
   Page authors can steer it with attributes:
     data-say="text"     speak this instead of the element's own text
     data-voice-skip     never read this element
*/
(function () {
  "use strict";
  var node = document.getElementById("sb-voice");
  if (!node) return;
  var C = JSON.parse(node.textContent), T0 = C.t;
  function T(s, v) {
    var out = T0[s] || s;
    if (v) for (var k in v) out = out.split("{" + k + "}").join(v[k]);
    return out;
  }
  var synth = window.speechSynthesis, supported = !!(synth && window.SpeechSynthesisUtterance);

  var store = {
    get: function (k, d) { try { var v = localStorage.getItem("sbv_" + k); return v === null ? d : v; } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem("sbv_" + k, v); } catch (e) {} }
  };
  var rate = store.get("rate", "0.9") === "0.7" ? 0.7 : 0.9;
  var auto = store.get("auto", "0") === "1";

  /* ---------- what to say ---------- */
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, SVG: 1, BUTTON: 1, SELECT: 1, INPUT: 1, TEXTAREA: 1, NAV: 1, IFRAME: 1 };
  var NESTED = "p,li,tr,div,section,article,ul,ol,table,h1,h2,h3,h4,dl,details,form,label,button,a.btn,a.act";
  var EMOJI = /[\u{1F000}-\u{1FAFF}\u{2190}-\u{21FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}️‍]/gu;

  function hidden(el) {
    if (el.hidden || el.getAttribute("aria-hidden") === "true" || el.hasAttribute("data-voice-skip")) return true;
    var cs = getComputedStyle(el);
    return cs.display === "none" || cs.visibility === "hidden";
  }
  function clean(t) {
    t = (t || "").replace(EMOJI, " ");
    t = t.replace(/₹\s?([\d,]+(?:\.\d+)?)/g, "$1 " + T("rupees"));
    t = t.replace(/(\d)\s?%/g, "$1 " + T("percent")).replace(/[|•·→←↑↓▲▼]/g, ", ");
    return t.replace(/\s*\n\s*/g, ". ").replace(/\s+/g, " ").replace(/(\.\s*){2,}/g, ". ").trim();
  }
  function plain(el) { return clean(el.innerText || el.textContent); }
  function firstLine(el) { return clean((el.innerText || el.textContent || "").split("\n").filter(function (l) { return l.trim(); })[0] || ""); }

  function readable(root) {
    var out = [];
    (function walk(el) {
      if (SKIP_TAGS[el.tagName.toUpperCase()] || hidden(el) || el.id === "sbv" || el.classList.contains("sbv")) return;
      if (el.hasAttribute("data-say")) { var s = clean(el.getAttribute("data-say")); if (s) out.push({ text: s, el: el }); return; }
      if (el.tagName === "TR") {
        var cells = [].map.call(el.children, plain).filter(Boolean);
        if (cells.length) out.push({ text: cells.join(", "), el: el });
        return;
      }
      if (!el.querySelector(NESTED)) { var t = plain(el); if (t) out.push({ text: t, el: el }); return; }
      [].forEach.call(el.children, walk);
    })(root);
    return out;
  }

  function labelOf(f) {
    var t = "";
    if (f.labels && f.labels[0]) t = plain(f.labels[0]);
    return t || clean(f.getAttribute("aria-label") || f.placeholder || f.name || "");
  }
  function shown(el) { for (var e = el; e && e !== document.body; e = e.parentElement) if (hidden(e)) return false; return true; }

  function actions() {
    var main = document.querySelector("main") || document.body, out = [];
    var h = main.querySelector("h1") || main.querySelector("h2");
    if (h) out.push({ text: T("You are on: {title}", { title: plain(h) }), el: h });
    [].forEach.call(main.querySelectorAll(".msgs li, .errorlist li, .err"), function (m) {
      if (shown(m)) { var t = plain(m); if (t) out.push({ text: T("Please note:") + " " + t, el: m }); }
    });
    var seen = {};
    [].forEach.call(main.querySelectorAll("input,select,textarea"), function (f) {
      if (f.type === "hidden" || f.type === "submit" || f.type === "button" || f.type === "radio" || f.disabled || !shown(f)) return;
      var name = labelOf(f); if (!name || seen["f" + name]) return; seen["f" + name] = 1;
      var key = f.tagName === "SELECT" ? "Choose {name}" : f.type === "checkbox" ? "Tick the box: {name}" : "Fill in {name}";
      out.push({ text: T(key, { name: name }), el: f });
    });
    // An element with data-say-do explains its own buttons in one sentence (e.g. a grid of crop pictures).
    var guided = [].filter.call(main.querySelectorAll("[data-say-do]"), shown);
    guided.forEach(function (g) { out.push({ text: clean(g.getAttribute("data-say-do")), el: g }); });
    var btns = [].filter.call(main.querySelectorAll("button, a.btn, a.act, [role=button]"), function (b) {
      return shown(b) && !b.disabled && !b.closest(".sbv") && firstLine(b) && !b.closest("nav") &&
        !guided.some(function (g) { return g.contains(b); });
    });
    var primary = btns.filter(function (b) { return !b.classList.contains("ghost"); });
    btns = primary.concat(btns.filter(function (b) { return primary.indexOf(b) < 0; }));
    var names = [], els = [];
    btns.forEach(function (b) { var n = firstLine(b); if (n.length <= 60 && names.indexOf(n) < 0) { names.push(n); els.push(b); } });
    if (names.length) {
      var shownN = names.slice(0, 6), more = names.length - shownN.length;
      var list = shownN.join(", ") + (more > 0 ? ", " + T("and {n} more options", { n: more }) : "");
      out.push({ text: T("You can tap: {list}", { list: list }), el: els[0], els: els.slice(0, 6) });
    }
    if (out.length <= 1) out.push({ text: T("There is nothing to do on this page. Tap Read this screen to listen to it."), el: null });
    return out;
  }

  /* ---------- speaking ---------- */
  var chunks = [], idx = 0, gen = 0, state = "idle", mode = "page", note = "";
  var voice = null;
  function pickVoice() {
    var vs = synth.getVoices(); voice = null;
    if (!vs.length) return;
    var want = C.speech.toLowerCase(), base = want.slice(0, 2);
    var by = function (f) { for (var i = 0; i < vs.length; i++) if (f(vs[i].lang.toLowerCase().replace("_", "-"))) return vs[i]; return null; };
    voice = by(function (l) { return l === want; }) || by(function (l) { return l.slice(0, 2) === base; });
    if (!voice && base === "mr") voice = by(function (l) { return l.slice(0, 2) === "hi"; }); // Hindi voices read Marathi's script
    note = !voice && base !== "en" ? T("This phone has no voice for your language. Install one in the phone's text-to-speech settings.") : "";
  }
  if (supported) { pickVoice(); if (synth.addEventListener) synth.addEventListener("voiceschanged", function () { pickVoice(); paint(); }); }

  function pieces(text) {
    var parts = text.match(/[^.!?।]+[.!?।]?/g) || [text], out = [], cur = "";
    parts.forEach(function (p) {
      if ((cur + p).length > 160 && cur) { out.push(cur); cur = p; } else cur += p;
    });
    if (cur.trim()) out.push(cur);
    return out;
  }
  function mark(c) {
    [].forEach.call(document.querySelectorAll(".sbv-on"), function (e) { e.classList.remove("sbv-on"); });
    if (!c) return;
    (c.els || (c.el ? [c.el] : [])).forEach(function (e) { if (e.isConnected) e.classList.add("sbv-on"); });
    if (c.el && c.el.isConnected && c.el.scrollIntoView) c.el.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  function speakChunk() {
    var my = gen;
    if (idx >= chunks.length) { finish(); return; }
    var c = chunks[idx]; mark(c);
    var ps = pieces(c.text), n = 0;
    (function next() {
      if (my !== gen) return;
      if (n >= ps.length) { idx++; speakChunk(); return; }
      var u = new SpeechSynthesisUtterance(ps[n++]);
      u.lang = C.speech; u.rate = rate; if (voice) u.voice = voice;
      u.onend = next;
      u.onerror = function (e) {
        if (my !== gen) return;
        if (e.error === "not-allowed") { state = "idle"; note = T("Tap Read to start listening."); mark(null); paint(); return; }
        if (e.error !== "interrupted" && e.error !== "canceled") next();
      };
      synth.speak(u);
    })();
  }
  function start(list, m) {
    if (!supported) return;
    synth.cancel(); gen++;
    chunks = list; idx = 0; mode = m; state = "playing";
    if (!chunks.length) chunks = [{ text: T("Nothing on this screen to read."), el: null }];
    note = voice || C.speech.slice(0, 2) === "en" ? "" : note;
    paint(); speakChunk();
  }
  function finish() { state = "idle"; mark(null); paint(); }
  function stop() { gen++; if (supported) synth.cancel(); state = "idle"; mode = "idle"; mark(null); paint(); }
  function pause() { if (state !== "playing") return; gen++; synth.cancel(); state = "paused"; paint(); }
  function resume() { if (state !== "paused") return; state = "playing"; gen++; paint(); speakChunk(); }
  function readPage() { start(readable(document.querySelector("main") || document.body), "page"); }
  function readActions() { start(actions(), "do"); }

  /* ---------- the control, fixed on the right ---------- */
  var root = document.createElement("div");
  root.id = "sbv"; root.className = "sbv";
  var open = false;
  document.body.appendChild(root);

  function btn(cls, icon, label, act) {
    return '<button type="button" class="sbv-b ' + cls + '" data-act="' + act + '"><span aria-hidden="true">' + icon + "</span> " + label + "</button>";
  }
  function paint() {
    var playing = state === "playing", paused = state === "paused";
    var h = '<button type="button" class="sbv-tab' + (playing ? " live" : "") + '" data-act="toggle" aria-expanded="' + open + '" aria-controls="sbv-panel" aria-label="' + T("Listen to this screen") + '">' +
      '<span class="ic" aria-hidden="true">' + (playing ? "🔊" : "🔈") + '</span><span class="lb">' + T("Listen") + "</span></button>";
    if (open) {
      h = '<div class="sbv-panel" id="sbv-panel" role="group" aria-label="' + T("Listen") + '">' +
        '<div class="sbv-head"><b>' + T("Listen") + '</b><button type="button" class="sbv-x" data-act="toggle" aria-label="' + T("Close") + '">✕</button></div>' +
        (supported ? btn("big", "▶", T("Read this screen"), "page") + btn("big alt", "☝", T("What should I do here?"), "do") +
          (playing ? btn("", "⏸", T("Pause"), "pause") + btn("", "⏹", T("Stop"), "stop") : "") +
          (paused ? btn("", "▶", T("Resume"), "resume") + btn("", "⏹", T("Stop"), "stop") : "") +
          '<div class="sbv-row">' + btn(rate === 0.7 ? "" : "on", "🐇", T("Normal voice"), "fast") + btn(rate === 0.7 ? "on" : "", "🐢", T("Slow voice"), "slow") + "</div>" +
          '<label class="sbv-auto"><input type="checkbox" data-act="auto"' + (auto ? " checked" : "") + "> " + T("Keep reading new screens") + "</label>" +
          '<p class="sbv-status" aria-live="polite">' + (playing ? T("Reading...") : paused ? T("Paused") : "") + (note ? " " + note : "") + "</p>"
          : '<p class="sbv-status">' + T("This phone cannot read aloud. Try the Chrome browser.") + "</p>") +
        "</div>" + h;
    }
    root.innerHTML = h;
  }
  root.addEventListener("click", function (e) {
    var t = e.target.closest("[data-act]"); if (!t) return;
    var a = t.getAttribute("data-act");
    if (a === "toggle") { open = !open; paint(); var f = root.querySelector(open ? ".sbv-b" : ".sbv-tab"); if (f) f.focus(); }
    else if (a === "page") readPage();
    else if (a === "do") readActions();
    else if (a === "pause") pause();
    else if (a === "resume") resume();
    else if (a === "stop") stop();
    else if (a === "slow" || a === "fast") { rate = a === "slow" ? 0.7 : 0.9; store.set("rate", String(rate)); paint(); }
  });
  root.addEventListener("change", function (e) {
    if (e.target.getAttribute("data-act") === "auto") { auto = e.target.checked; store.set("auto", auto ? "1" : "0"); }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && open) { open = false; paint(); root.querySelector(".sbv-tab").focus(); } });
  window.addEventListener("pagehide", function () { if (supported) synth.cancel(); });
  paint();

  /* ---------- for pages that change without reloading (the calculator) ---------- */
  var timer = null;
  window.sbVoice = {
    say: function (text) { open = true; start([{ text: clean(text), el: null }], "say"); },
    stop: stop,
    changed: function () {
      if (!auto || !supported || state === "idle" && mode === "idle") return;
      clearTimeout(timer);
      timer = setTimeout(function () { if (auto && state !== "paused" && mode !== "say") (mode === "do" ? readActions : readPage)(); }, 350);
    }
  };
  /* "keep reading" starts only after the farmer has pressed a read button once on this page */
  mode = "idle";
})();
