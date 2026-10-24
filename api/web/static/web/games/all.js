/* The twelve games. Each takes the stage element and the engine `g` (see core.js). Kept simple, big and readable. */
(function () {
  "use strict";
  var R = SBG.register;

  /* Multiple-choice rounds used by the quiz and weather games: tap or say the option number or words. */
  function choiceRounds(stage, g, items, perRight, perWrong) {
    var list = g.shuffle(items).slice(0, 10), i = 0;
    function show() {
      stage.innerHTML = "";
      if (i >= list.length) return g.end();
      var it = list[i], order = g.shuffle(it.opts.map(function (o, k) { return k; }));
      stage.appendChild(g.el("p", "mute", (i + 1) + " / " + list.length));
      var q = g.el("h2", "q", it.q); stage.appendChild(q); g.speak(it.q);
      var box = g.el("div", "opts");
      var answer = function (pos) {
        var ok = order[pos] === it.a;
        g.add(ok ? perRight : perWrong); g.flash(ok, it.why); i++;
        box.querySelectorAll("button").forEach(function (b, k) { b.disabled = true; if (order[k] === it.a) b.classList.add("right"); });
        g.later(show, 2200);
      };
      order.forEach(function (k, pos) {
        var b = g.el("button", "btn opt", (pos + 1) + ". " + it.opts[k]); b.type = "button";
        b.addEventListener("click", function () { answer(pos); }); box.appendChild(b);
      });
      stage.appendChild(box);
      stage.appendChild(g.mic(function () { return order.map(function (k) { return [it.opts[k]]; }); }, function (pos) { if (pos >= 0) answer(pos); else g.flash(false, g.T("Try again")); }));
    }
    show();
  }

  R("quiz", function (stage, g) { choiceRounds(stage, g, g.data.items, 10, 0); });
  R("weather", function (stage, g) { choiceRounds(stage, g, g.data.items, 12, 0); });

  R("price", function (stage, g) {
    var list = g.shuffle(g.data.items).slice(0, 5), i = 0;
    if (!list.length) { stage.appendChild(g.el("p", null, g.T("No mandi price is available for this crop today."))); return g.end(); }
    function show() {
      stage.innerHTML = "";
      if (i >= list.length) return g.end();
      var it = list[i], guess = Math.round(it.price * (0.6 + Math.random() * 0.8) / 50) * 50;
      stage.appendChild(g.el("div", "emoji-xl", it.emoji));
      stage.appendChild(g.el("h2", "q", it.name)); g.speak(it.name);
      stage.appendChild(g.el("label", "mute", g.T("Your guess (₹ per quintal)")));
      var out = g.el("div", "big"), range = document.createElement("input");
      range.type = "range"; range.min = Math.round(it.price * 0.3); range.max = Math.round(it.price * 1.8); range.step = 10; range.value = guess; range.className = "slider";
      var paint = function () { out.textContent = "₹" + Number(range.value).toLocaleString("en-IN"); };
      range.addEventListener("input", paint); paint();
      stage.appendChild(out); stage.appendChild(range);
      var check = g.el("button", "btn", g.T("Check")); check.type = "button";
      check.addEventListener("click", function () {
        var off = Math.abs(range.value - it.price) / it.price, pts = Math.max(0, Math.round(20 * (1 - off * 2.5)));
        g.add(pts); g.flash(pts >= 10, g.T("Today's mandi price") + ": ₹" + it.price.toLocaleString("en-IN")); i++; check.disabled = true; g.later(show, 2200);
      });
      stage.appendChild(check);
      stage.appendChild(g.mic([], function (k, heard) {
        var n = parseInt((heard || "").replace(/[^0-9]/g, ""), 10);
        if (n) { range.value = n; paint(); check.click(); } else g.flash(false, g.T("Try again"));
      }));
    }
    show();
  });

  R("season", function (stage, g) {
    var list = g.shuffle(g.data.items).slice(0, 10), i = 0, words = g.data.words;
    function show() {
      stage.innerHTML = "";
      if (i >= list.length) return g.end();
      var it = list[i];
      stage.appendChild(g.el("div", "emoji-xl", it.emoji)); stage.appendChild(g.el("h2", "q", it.name)); g.speak(it.name);
      var pick = function (s) { var ok = s === it.season; g.add(ok ? 10 : 0); g.flash(ok, ok ? g.T("Correct!") : (it.season === "kharif" ? g.T("Kharif") : g.T("Rabi"))); i++; g.later(show, 1300); };
      var row = g.el("div", "opts two");
      [["kharif", "🌧️ " + g.T("Kharif")], ["rabi", "❄️ " + g.T("Rabi")]].forEach(function (p) { var b = g.el("button", "btn opt", p[1]); b.type = "button"; b.addEventListener("click", function () { pick(p[0]); }); row.appendChild(b); });
      stage.appendChild(row);
      stage.appendChild(g.mic([words.kharif, words.rabi], function (k) { if (k >= 0) pick(k === 0 ? "kharif" : "rabi"); else g.flash(false, g.T("Try again")); }));
    }
    show();
  });

  R("pests", function (stage, g) {
    var grid = g.el("div", "grid-tiles"), left = 30, timeEl = g.el("p", "mute");
    stage.appendChild(timeEl); stage.appendChild(grid);
    var cells = [];
    for (var k = 0; k < 12; k++) { var c = g.el("button", "tile-btn", ""); c.type = "button"; grid.appendChild(c); cells.push(c); }
    function fill() {
      cells.forEach(function (c) {
        var foe = Math.random() < 0.5, pool = foe ? g.data.foes : g.data.friends;
        c.textContent = pool[Math.floor(Math.random() * pool.length)]; c.dataset.foe = foe ? "1" : "0"; c.disabled = false; c.classList.remove("hit", "miss");
      });
    }
    cells.forEach(function (c) { c.addEventListener("click", function () {
      if (c.disabled) return; c.disabled = true;
      if (c.dataset.foe === "1") { g.add(2); c.classList.add("hit"); } else { g.add(-3); c.classList.add("miss"); g.flash(false); }
      if (cells.every(function (x) { return x.disabled || x.dataset.foe === "0"; })) g.later(fill, 300);
    }); });
    fill();
    var tick = function () { timeEl.textContent = g.T("Time") + ": " + left + "s"; if (left-- <= 0) g.end(g.data.lessons.join(" ")); };
    tick(); g.every(tick, 1000); g.every(fill, 6000);
  });

  R("memory", function (stage, g) {
    var pairs = g.shuffle(g.data.pairs).slice(0, 6), cards = [];
    pairs.forEach(function (p, i) { cards.push({ id: i, side: p[0] }); cards.push({ id: i, side: p[1] }); });
    cards = g.shuffle(cards);
    var grid = g.el("div", "grid-tiles mem"), open = [], found = 0, moves = 0, info = g.el("p", "mute");
    stage.appendChild(info); stage.appendChild(grid);
    var paint = function () { info.textContent = g.T("Pairs found") + ": " + found + " / " + pairs.length + " · " + g.T("Moves") + ": " + moves; };
    cards.forEach(function (c) {
      var b = g.el("button", "tile-btn card-back", "?"); b.type = "button";
      b.addEventListener("click", function () {
        if (b.classList.contains("up") || open.length === 2) return;
        b.classList.add("up"); b.innerHTML = ""; b.appendChild(g.el("span", "e", c.side.emoji)); b.appendChild(g.el("small", null, c.side.name)); g.speak(c.side.name);
        open.push({ b: b, c: c });
        if (open.length === 2) {
          moves++;
          var a = open[0], z = open[1];
          if (a.c.id === z.c.id) { found++; g.add(15); open = []; a.b.classList.add("hit"); z.b.classList.add("hit"); if (found === pairs.length) { g.add(Math.max(0, 20 - moves)); g.later(function () { g.end(); }, 600); } }
          else g.later(function () { [a, z].forEach(function (o) { o.b.classList.remove("up"); o.b.textContent = "?"; }); open = []; }, 900);
          paint();
        }
      });
      grid.appendChild(b);
    });
    paint();
  });

  R("catch", function (stage, g) {
    var cv = document.createElement("canvas"), W = Math.min(stage.clientWidth || 360, 480), H = 420;
    cv.width = W; cv.height = H; cv.className = "playfield"; stage.appendChild(cv);
    var ctx = cv.getContext("2d"), x = W / 2, items = [], lives = 3, t = 0;
    var move = function (cx) { var r = cv.getBoundingClientRect(); x = Math.max(30, Math.min(W - 30, (cx - r.left) * W / r.width)); };
    cv.addEventListener("pointermove", function (e) { move(e.clientX); }); cv.addEventListener("pointerdown", function (e) { move(e.clientX); });
    ctx.font = "28px sans-serif"; ctx.textAlign = "center";
    g.every(function () {
      t++;
      if (t % 18 === 0) items.push({ x: 20 + Math.random() * (W - 40), y: -10, v: 2.5 + Math.random() * 2 + t / 900, stone: Math.random() < 0.28 });
      ctx.fillStyle = "#e8f5ec"; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#14532d"; ctx.font = "16px sans-serif"; ctx.textAlign = "left"; ctx.fillText("❤️".repeat(lives), 8, 22); ctx.textAlign = "center"; ctx.font = "28px sans-serif";
      items.forEach(function (it) {
        it.y += it.v; ctx.fillText(it.stone ? "🪨" : "🌾", it.x, it.y);
        if (it.y > H - 40 && it.y < H - 10 && Math.abs(it.x - x) < 36) { it.done = true; if (it.stone) { lives--; g.flash(false); } else g.add(2); }
        if (it.y > H + 20) it.done = true;
      });
      items = items.filter(function (it) { return !it.done; });
      ctx.font = "40px sans-serif"; ctx.fillText("🧺", x, H - 12); ctx.font = "28px sans-serif";
      if (lives <= 0 || t > 1800) g.end();
    }, 33);
  });

  R("water", function (stage, g) {
    var m = 50, left = 40, irrigating = false, weather = "sun";
    var bar = g.el("div", "meter"), fill = g.el("div", "meter-fill"), label = g.el("p", "big"), sky = g.el("div", "emoji-xl", "☀️"), timeEl = g.el("p", "mute");
    bar.appendChild(fill);
    stage.appendChild(sky); stage.appendChild(g.el("p", "mute", g.T("Soil moisture"))); stage.appendChild(bar); stage.appendChild(label); stage.appendChild(timeEl);
    var row = g.el("div", "opts two"), wb = g.el("button", "btn opt", "💧 " + g.T("Water")), sb = g.el("button", "btn opt", "✋ " + g.T("Stop"));
    wb.type = sb.type = "button"; wb.addEventListener("click", function () { irrigating = true; }); sb.addEventListener("click", function () { irrigating = false; });
    row.appendChild(wb); row.appendChild(sb); stage.appendChild(row);
    var voice = g.mic([["water", "pani", "पानी", "पाणी"], ["stop", "ruko", "रुको", "बंद", "थांबा"]], function (k) { if (k === 0) irrigating = true; else if (k === 1) irrigating = false; });
    stage.appendChild(voice);
    g.every(function () {
      if (Math.random() < 0.08) { weather = weather === "sun" ? "rain" : "sun"; sky.textContent = weather === "sun" ? "☀️" : "🌧️"; g.speak(weather === "sun" ? g.T("Sun") : g.T("Rain")); }
      m += (irrigating ? 4 : 0) + (weather === "rain" ? 3 : -2.5);
      m = Math.max(0, Math.min(100, m));
      fill.style.width = m + "%"; fill.className = "meter-fill " + (m < 35 ? "dry" : m > 75 ? "wet" : "ok");
      label.textContent = m < 35 ? g.T("Too dry") : m > 75 ? g.T("Too wet") : g.T("Just right");
      if (m >= 35 && m <= 75) g.add(1);
      wb.classList.toggle("on", irrigating);
    }, 500);
    g.every(function () { timeEl.textContent = g.T("Time") + ": " + left + "s"; if (left-- <= 0) g.end(); }, 1000);
  });

  R("market", function (stage, g) {
    var crops = g.data.crops, i = 0;
    function show() {
      stage.innerHTML = "";
      if (i >= 6) return g.end();
      var c = crops[Math.floor(Math.random() * crops.length)], q = 10 + Math.floor(Math.random() * 30);
      var opts = [
        { label: g.T("Mandi A"), rate: Math.round(c.price * (0.95 + Math.random() * 0.15)), comm: 2 + Math.floor(Math.random() * 3), trans: 300 + Math.floor(Math.random() * 6) * 100 },
        { label: g.T("Mandi B"), rate: Math.round(c.price * (0.95 + Math.random() * 0.2)), comm: 1 + Math.floor(Math.random() * 3), trans: 800 + Math.floor(Math.random() * 15) * 100 },
        { label: g.T("Direct buyer"), rate: Math.round(c.price * (0.9 + Math.random() * 0.2)), comm: 0, trans: Math.floor(Math.random() * 5) * 100 }];
      opts.forEach(function (o) { o.hand = Math.round(q * o.rate * (1 - o.comm / 100) - o.trans); });
      var best = opts.reduce(function (b, o, k) { return o.hand > opts[b].hand ? k : b; }, 0);
      stage.appendChild(g.el("h2", "q", c.name + " · " + q + " q"));
      stage.appendChild(g.el("p", "mute", g.T("Which gives the most money in hand?"))); g.speak(g.T("Which gives the most money in hand?"));
      var box = g.el("div", "opts");
      var pick = function (k) {
        var ok = k === best; g.add(ok ? 15 : 0);
        g.flash(ok, opts[best].label + " · " + g.T("Money in hand") + " ₹" + opts[best].hand.toLocaleString("en-IN")); i++; g.later(show, 2400);
      };
      opts.forEach(function (o, k) {
        var b = g.el("button", "btn opt left", ""); b.type = "button";
        b.innerHTML = "<b>" + (k + 1) + ". " + o.label + "</b><br><small>" + g.T("Rate") + " ₹" + o.rate.toLocaleString("en-IN") + " · " + g.T("Commission") + " " + o.comm + "% · " + g.T("Transport") + " ₹" + o.trans + "</small>";
        b.addEventListener("click", function () { pick(k); }); box.appendChild(b);
      });
      stage.appendChild(box);
      stage.appendChild(g.mic(opts.map(function (o) { return [o.label]; }), function (k) { if (k >= 0) pick(k); }));
    }
    show();
  });

  R("sums", function (stage, g) {
    var crops = g.data.crops, i = 0;
    function show() {
      stage.innerHTML = "";
      if (i >= 8) return g.end();
      var c = crops[Math.floor(Math.random() * crops.length)], q = 2 + Math.floor(Math.random() * 25), rate = Math.round(c.price / 10) * 10, total = q * rate;
      var opts = g.shuffle([total, total + rate * (1 + Math.floor(Math.random() * 3)), Math.max(rate, total - rate * (1 + Math.floor(Math.random() * 3)))]);
      var text = q + " q × ₹" + rate.toLocaleString("en-IN");
      stage.appendChild(g.el("p", "mute", c.name)); stage.appendChild(g.el("h2", "q", text)); g.speak(g.T("Which is the right total?"));
      var box = g.el("div", "opts"), t0 = Date.now();
      var pick = function (k) { var ok = opts[k] === total; g.add(ok ? Math.max(6, 14 - Math.floor((Date.now() - t0) / 1500)) : 0); g.flash(ok, "₹" + total.toLocaleString("en-IN")); i++; g.later(show, 1600); };
      opts.forEach(function (v, k) { var b = g.el("button", "btn opt", (k + 1) + ". ₹" + v.toLocaleString("en-IN")); b.type = "button"; b.addEventListener("click", function () { pick(k); }); box.appendChild(b); });
      stage.appendChild(box);
      stage.appendChild(g.mic(opts.map(function (v) { return [String(v)]; }), function (k) { if (k >= 0) pick(k); }));
    }
    show();
  });

  R("name", function (stage, g) {
    var list = g.shuffle(g.data.items).slice(0, 8), i = 0;
    function show() {
      stage.innerHTML = "";
      if (i >= list.length) return g.end();
      var it = list[i], others = g.shuffle(g.data.items.filter(function (x) { return x.k !== it.k; })).slice(0, 2), opts = g.shuffle([it].concat(others));
      stage.appendChild(g.el("div", "emoji-xl", it.emoji)); stage.appendChild(g.el("p", "mute", g.T("Say the name of this crop")));
      var heardEl = g.el("p", "mute");
      var done = function (ok, viaVoice) { g.add(ok ? (viaVoice ? 15 : 8) : 0); g.flash(ok, it.name); i++; g.later(show, 1500); };
      var mic = g.mic([it.say], function (k, heard) { heardEl.textContent = heard ? g.T("I heard: {text}", { text: heard }) : ""; if (k === 0) done(true, true); else g.flash(false, g.T("Try again")); });
      stage.appendChild(mic); stage.appendChild(heardEl);
      var box = g.el("div", "opts");
      opts.forEach(function (o) { var b = g.el("button", "btn opt", o.name); b.type = "button"; b.addEventListener("click", function () { done(o.k === it.k, false); }); box.appendChild(b); });
      stage.appendChild(box);
    }
    show();
  });

  R("sow", function (stage, g) {
    var cv = document.createElement("canvas"), W = Math.min(stage.clientWidth || 360, 480), H = 200;
    cv.width = W; cv.height = H; cv.className = "playfield"; stage.appendChild(cv);
    var ctx = cv.getContext("2d"), pos = 0, speed = 3, dir = 1, hits = 0, tries = 0, zone = W / 2;
    var tap = g.el("button", "btn block", "🌱 " + g.T("Tap now!")); tap.type = "button"; stage.appendChild(tap);
    var press = function () {
      tries++;
      var off = Math.abs(pos - zone);
      if (off < 14) { g.add(10); hits++; g.flash(true); } else if (off < 34) { g.add(5); g.flash(true); } else g.flash(false);
      zone = 40 + Math.random() * (W - 80); speed += 0.4;
      if (tries >= 10) g.later(function () { g.end(); }, 400);
    };
    tap.addEventListener("click", press); cv.addEventListener("pointerdown", press);
    g.every(function () {
      pos += speed * dir; if (pos > W - 10 || pos < 10) dir = -dir;
      ctx.fillStyle = "#8b5e34"; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#6b4423"; for (var y = 30; y < H; y += 40) ctx.fillRect(0, y, W, 8);
      ctx.fillStyle = "rgba(31,122,63,.55)"; ctx.fillRect(zone - 14, 0, 28, H);
      ctx.font = "34px sans-serif"; ctx.textAlign = "center"; ctx.fillText("🌰", pos, H / 2 + 12);
    }, 30);
  });
})();
