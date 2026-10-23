/* Harvest calculator: one question per screen, rates filled in from today's mandi prices, everything else by tapping.
 * sbCompute holds the arithmetic so it can be tested without a browser (rates/calc.py is the server copy). */
(function (root) {
  var KG = { kg: 1, quintal: 100, tonne: 1000 };
  function n(v) { v = parseFloat(v); return isFinite(v) && v > 0 ? v : 0; }
  function round(x) { return Math.round(x * 100) / 100; }

  function sbCompute(i) {
    var unit = i.unit || "quintal";
    var perUnit = unit === "bag" ? n(i.bagKg) : (KG[unit] || 100);
    var qtl = n(i.qty) * perUnit / 100;
    var ratePerQtl = n(i.rate) * (i.rateUnit === "kg" ? 100 : 1);
    var gross = qtl * ratePerQtl;
    var commission = gross * n(i.commissionPct) / 100;
    var cut = commission + n(i.fees) + n(i.other);
    var hand = gross - cut - n(i.transport);
    var out = { gross: round(gross), commission: round(commission), cut: round(cut), hand: round(hand) };
    if (n(i.directRate) > 0 && qtl > 0) {
      out.direct = round(qtl * n(i.directRate) - n(i.directTransport));
      out.gap = round(out.direct - hand);
    }
    return out;
  }

  if (typeof module !== "undefined") module.exports = { sbCompute: sbCompute };
  root.sbCompute = sbCompute;
  if (typeof document === "undefined" || !document.getElementById("calc-data")) return;

  var D = JSON.parse(document.getElementById("calc-data").textContent);
  var $ = function (id) { return document.getElementById(id); };
  var wiz = $("wiz");
  var STEPS = ["crop", "qty", "rate", "cuts", "compare", "result"];
  var KEY = "sb_calc_v2";
  var Q = null, quoteFor = "", loading = false, failed = false;

  function T(key, vars) {
    var s = (D.strings && D.strings[key]) || key;
    if (vars) Object.keys(vars).forEach(function (k) { s = s.split("{" + k + "}").join(vars[k]); });
    return s;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function inr(x) {
    var neg = x < 0, s = Math.abs(Math.round(x)).toString(), last = s.slice(-3), rest = s.slice(0, -3);
    if (rest) last = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last;
    return (neg ? "-" : "") + "₹" + last;
  }
  function fmtDate(iso) { var d = new Date(iso + "T00:00:00"); return d.toLocaleDateString(D.speech, { day: "numeric", month: "short" }); }
  function cropOf(key) { return D.crops.filter(function (c) { return c.crop === key; })[0] || { label: key, emoji: "🌾" }; }

  var blank = { step: "crop", crop: "", qty: "", unit: "quintal", bagKg: "50", rate: "", rateUnit: "quintal", rateLabel: "", commissionPct: "0", fees: "0", other: "0", transport: "0", directRate: "", directTransport: "0", directLabel: "" };
  var S = (function () { try { return Object.assign({}, blank, JSON.parse(sessionStorage.getItem(KEY) || "{}")); } catch (e) { return Object.assign({}, blank); } })();
  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} }
  function go(step) { S.step = step; save(); render(); window.scrollTo({ top: wiz.offsetTop - 80, behavior: "smooth" }); }
  function toast(msg) { var t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.h); toast.h = setTimeout(function () { t.hidden = true; }, 6000); }

  function dots() {
    var i = STEPS.indexOf(S.step);
    return '<div class="dots" aria-hidden="true">' + STEPS.map(function (_, k) { return '<i class="' + (k <= i ? "on" : "") + '"></i>'; }).join("") + "</div>";
  }
  function nav(nextLabel, nextDisabled, extra) {
    var i = STEPS.indexOf(S.step);
    return '<div class="wiz-nav">' + (i > 0 ? '<button class="btn ghost" data-act="back">← ' + T("Back") + "</button>" : "<span></span>") +
      (nextLabel ? '<button class="btn" id="next" data-act="next"' + (nextDisabled ? " disabled" : "") + ">" + nextLabel + " →</button>" : "") + (extra || "") + "</div>";
  }
  function chips(name, values, current, prefix) {
    return '<div class="chip-row">' + values.map(function (v) {
      return '<button type="button" class="chip' + (String(current) === String(v) ? " on" : "") + '" data-act="chip" data-f="' + name + '" data-v="' + v + '">' + (prefix || "") + v + "</button>";
    }).join("") + "</div>";
  }

  /* ---------- steps ---------- */
  function stepCrop() {
    var tiles = D.crops.map(function (c) {
      return '<button class="tile' + (S.crop === c.crop ? " on" : "") + '" data-act="crop" data-v="' + c.crop + '" data-name="' + esc(c.label.toLowerCase()) + '"><span class="e">' + c.emoji + "</span><b>" + esc(c.label) + "</b>" +
        (c.typical ? "<small>" + inr(c.typical) + "</small>" : "") + "</button>";
    }).join("");
    return "<h2>" + T("Which crop do you want to sell?") + '</h2><input type="search" id="crop-search" placeholder="' + T("Search crop") + '" autocomplete="off"><div class="tiles" id="tiles" data-say-do="' + esc(T("Tap the picture of your crop. If you cannot see it, type its name in the search box.")) + '">' + tiles + "</div>";
  }

  var QTY_STEP = { quintal: 1, kg: 10, tonne: 0.5, bag: 1 };
  var QTY_CHIPS = { quintal: [5, 10, 20, 50, 100], kg: [100, 500, 1000, 2000], tonne: [1, 2, 5, 10], bag: [10, 25, 50, 100] };
  function stepQty() {
    var c = cropOf(S.crop);
    var units = ["quintal", "kg", "bag", "tonne"].map(function (u) { return '<button type="button" class="seg-b' + (S.unit === u ? " on" : "") + '" data-act="unit" data-v="' + u + '">' + T(u === "quintal" ? "Quintal" : u === "kg" ? "Kg" : u === "bag" ? "Bag" : "Tonne") + "</button>"; }).join("");
    return '<div class="picked">' + c.emoji + " <b>" + esc(c.label) + "</b></div><h2>" + T("How much do you have?") + "</h2>" +
      '<div class="stepper"><button type="button" class="round" data-act="dec" aria-label="-">−</button><input id="qty" type="text" inputmode="decimal" value="' + esc(S.qty) + '" placeholder="0"><button type="button" class="round" data-act="inc" aria-label="+">+</button></div>' +
      '<div class="seg">' + units + "</div>" + chips("qty", QTY_CHIPS[S.unit]) +
      (S.unit === "bag" ? '<div class="field" style="margin-top:14px"><label for="bagkg">' + T("Weight of one bag (kg)") + '</label><input id="bagkg" type="text" inputmode="decimal" value="' + esc(S.bagKg) + '">' + chips("bagKg", [30, 40, 50, 60, 100], S.bagKg) + "</div>" : "") +
      nav(T("Next"), !n(S.qty));
  }

  function rateCard(label, price, sub, extra) {
    var on = S.rate && n(S.rate) === n(price) && S.rateLabel === extra.key;
    return '<button type="button" class="mk' + (on ? " on" : "") + '" data-act="rate" data-v="' + price + '" data-k="' + esc(extra.key) + '"><span><b>' + label + '</b><br><small>' + sub + '</small></span><i>' + inr(price) + "</i></button>";
  }
  function stepRate() {
    var c = cropOf(S.crop), body = "";
    if (loading) body = '<p class="mute">' + T("Loading rates...") + "</p>";
    else if (failed) body = '<p class="err">' + T("Rates could not be loaded. Type your own rate.") + "</p>";
    else if (Q && Q.typical) {
      var where = Q.scope === "district" ? Q.district : (Q.state || "");
      body += rateCard(T("Typical rate near you"), Q.typical, esc(where) + " · " + T("Reported on {date}", { date: fmtDate(Q.as_of) }), { key: "typical" });
      if ((Q.local || []).length > 1) Q.local.slice(0, 4).forEach(function (m) { body += rateCard(esc(m.market), m.modal, esc(m.district) + " · " + fmtDate(m.date), { key: "m:" + m.market }); });
      if (Q.msp) body += rateCard("🏛️ " + T("Govt MSP"), Q.msp.price, esc(Q.msp.season), { key: "msp" });
      if (Q.trend) body += '<p class="pill ' + (Q.trend > 0 ? "" : "red") + '">' + (Q.trend > 0 ? "▲ " + T("up {n}% this week", { n: Q.trend }) : "▼ " + T("down {n}% this week", { n: Math.abs(Q.trend) })) + "</p>";
      if (Q.sample_data) body += '<p class="err">' + T("Sample data, not real prices") + "</p>";
    } else body = '<p class="hint">' + T("No rate found near you for this crop. Type your own rate.") + "</p>";
    var own = S.rateLabel === "own";
    return '<div class="picked">' + c.emoji + " <b>" + esc(c.label) + "</b> · " + esc(S.qty) + " " + T(S.unit) + "</div><h2>" + T("Rate near you today") + "</h2>" + body +
      '<div class="field" style="margin-top:12px"><label for="own-rate">' + T("My own rate") + " — " + (S.rateUnit === "kg" ? T("Rate per kg (₹)") : T("Rate per quintal (₹)")) + '</label>' +
      '<div class="row"><input id="own-rate" type="text" inputmode="decimal" style="flex:1" value="' + (own ? esc(S.rate) : "") + '" placeholder="₹"><button type="button" class="chip" data-act="rateunit">' + (S.rateUnit === "kg" ? T("per kg") : T("per quintal")) + " ⇄</button></div></div>" +
      '<p class="hint">' + T("Rates are from mandis reported to Agmarknet (Govt. of India). Your mandi may differ.") + "</p>" + nav(T("Next"), !n(S.rate));
  }

  function stepCuts() {
    return "<h2>" + T("What does the mandi take from you?") + '</h2><p class="hint">' + T("Not sure? Leave 0. You can change it later.") + "</p>" +
      '<div class="field"><label>' + T("Commission (aadhat) %") + '</label><input id="f-commissionPct" data-f="commissionPct" type="text" inputmode="decimal" value="' + esc(S.commissionPct) + '">' + chips("commissionPct", [0, 1, 2, 3, 4], S.commissionPct) + "</div>" +
      '<div class="field"><label>' + T("Weighing and loading fees (₹)") + '</label><input id="f-fees" data-f="fees" type="text" inputmode="decimal" value="' + esc(S.fees) + '">' + chips("fees", [0, 100, 200, 300, 500], S.fees) + "</div>" +
      '<div class="field"><label>' + T("Transport to the mandi (₹)") + '</label><input id="f-transport" data-f="transport" type="text" inputmode="decimal" value="' + esc(S.transport) + '">' + chips("transport", [0, 500, 1000, 1500, 2000], S.transport) + "</div>" +
      '<div class="field"><label>' + T("Other cuts (₹)") + '</label><input id="f-other" data-f="other" type="text" inputmode="decimal" value="' + esc(S.other) + '"></div>' + nav(T("Next"), false);
  }

  function stepCompare() {
    var rows = (Q && Q.nearby) || [], body = "";
    if (rows.length) {
      body += '<p class="hint">' + T("Best prices in your state today") + "</p>";
      rows.slice(0, 5).forEach(function (m) {
        var on = S.directLabel === m.market;
        body += '<button type="button" class="mk' + (on ? " on" : "") + '" data-act="direct" data-v="' + m.modal + '" data-l="' + esc(m.market) + '"><span><b>' + esc(m.market) + "</b><br><small>" + esc(m.district) + " · " + fmtDate(m.date) + "</small></span><i>" + inr(m.modal) + "</i></button>";
      });
    }
    var picked = n(S.directRate) > 0;
    return "<h2>" + T("Compare with another market?") + "</h2>" + body +
      '<div class="field" style="margin-top:12px"><label for="direct-rate">' + T("A buyer offered me (₹ per quintal)") + '</label><input id="direct-rate" type="text" inputmode="decimal" value="' + (S.directLabel === "own" ? esc(S.directRate) : "") + '" placeholder="₹"></div>' +
      (picked ? '<div class="field"><label>' + T("Transport to that market (₹)") + '</label><input id="f-directTransport" data-f="directTransport" type="text" inputmode="decimal" value="' + esc(S.directTransport) + '">' + chips("directTransport", [0, 500, 1000, 2000, 3000], S.directTransport) + "</div>" : "") +
      nav(picked ? T("Next") : T("Skip"), false);
  }

  function summary() {
    var r = sbCompute(S), c = cropOf(S.crop), t = c.label + ", " + S.qty + " " + T(S.unit) + ". " + T("In your hand") + ": " + inr(r.hand) + ".";
    if (r.direct !== undefined) t += " " + T("Money in your hand from {place}", { place: S.directLabel === "own" ? "" : S.directLabel }).trim() + ": " + inr(r.direct) + ".";
    return t;
  }
  function stepResult() {
    var r = sbCompute(S), c = cropOf(S.crop), place = S.directLabel === "own" ? "" : S.directLabel;
    var h = '<div class="picked">' + c.emoji + " <b>" + esc(c.label) + "</b> · " + esc(S.qty) + " " + T(S.unit) + "</div><h2>" + T("Your result") + "</h2>" +
      '<div class="calc-out"><p class="mute" style="margin:0">' + T("Money in your hand at the mandi") + '</p><div class="big">' + inr(r.hand) + "</div>" +
      '<div class="calc-lines"><div><span>' + T("Value at the rate") + "</span><b>" + inr(r.gross) + "</b></div>" +
      '<div><span>− ' + T("Commission") + "</span><b>" + inr(r.commission) + "</b></div>" +
      '<div><span>− ' + T("Fees and other cuts") + "</span><b>" + inr(r.cut - r.commission) + "</b></div>" +
      '<div><span>− ' + T("Transport") + "</span><b>" + inr(n(S.transport)) + "</b></div></div>" +
      '<div class="zero">' + T("Seedha Bazar commission on your sale") + ": ₹0</div></div>";
    if (r.direct !== undefined) {
      var msg = r.gap > 0 ? T("A direct sale gives {amount} more at this rate", { amount: inr(r.gap) }) : r.gap < 0 ? T("The mandi gives {amount} more at this rate", { amount: inr(-r.gap) }) : T("No difference at these rates");
      h += '<div class="calc-out alt"><p class="mute" style="margin:0">' + T("Money in your hand from {place}", { place: place || "" }).trim() + '</p><div class="big">' + inr(r.direct) + '</div><p style="margin:8px 0 0"><b>' + msg + "</b></p></div>";
    }
    var login = "/login/?as=farmer&next=" + encodeURIComponent("/calculator/");
    var forSale = "/farmer/sell/new/?crop=" + encodeURIComponent(S.crop) + "&qty=" + encodeURIComponent(S.qty) + "&unit=" + S.unit + "&price=" + encodeURIComponent(S.rate);
    var canSell = !D.user.in || D.user.role === "farmer" || D.user.role === "agent";
    var sellUrl = D.user.in ? (D.user.role === "agent" ? "/fpo/sell/new/?crop=" + encodeURIComponent(S.crop) + "&qty=" + encodeURIComponent(S.qty) + "&unit=" + S.unit + "&price=" + encodeURIComponent(S.rate) : forSale) : "/login/?as=farmer&next=" + encodeURIComponent(forSale);
    h += '<p class="hint">' + T("This is an estimate. The real result depends on the buyer, the quality of your crop and transport.") + "</p>" +
      '<div class="actions">' +
      ("speechSynthesis" in window ? '<button class="act" data-act="speak">🔊 ' + T("Listen") + "</button>" : "") +
      (D.user.in ? '<button class="act whats" data-act="send" data-ch="whatsapp">💬 ' + T("Send to my WhatsApp") + '</button><button class="act" data-act="send" data-ch="sms">✉️ ' + T("Send to my phone as SMS") + "</button>"
        : '<a class="act whats" href="' + login + '">💬 ' + T("Sign in to get this on your phone") + "</a>") +
      '<a class="act" target="_blank" rel="noopener" href="https://wa.me/?text=' + encodeURIComponent(summary() + " — " + location.origin) + '" data-track="calc_share">📤 ' + T("Share on WhatsApp") + "</a>" +
      (canSell ? '<a class="act sell" href="' + sellUrl + '">🏷️ ' + T("List this crop for sale") + "</a>" : "") + "</div>" +
      '<div class="alertbox"><b>🔔 ' + T("Tell me {crop} rates every day", { crop: esc(c.label) }) + "</b><div class=\"row\" style=\"margin-top:8px\">" +
      (D.user.in ? '<button class="btn small ghost" data-act="alert" data-ch="whatsapp">WhatsApp</button><button class="btn small ghost" data-act="alert" data-ch="sms">SMS</button>' : '<a class="btn small ghost" href="' + login + '">' + T("Sign in to get this on your phone") + "</a>") + "</div></div>" +
      '<div class="wiz-nav"><button class="btn ghost" data-act="back">← ' + T("Back") + '</button><button class="btn" data-act="restart">↺ ' + T("Start over") + "</button></div>";
    $("payload").value = JSON.stringify({ crop: S.crop, inputs: S, result: r });
    return h;
  }

  /* ---------- rendering and events ---------- */
  function render() {
    var f = { crop: stepCrop, qty: stepQty, rate: stepRate, cuts: stepCuts, compare: stepCompare, result: stepResult }[S.step];
    wiz.innerHTML = dots() + f();
    $("lead-card").hidden = S.step !== "result";
    if (S.step === "rate" || S.step === "compare") ensureQuote();
    if (window.sbVoice) window.sbVoice.changed();
  }

  function ensureQuote() {
    if (!S.crop || (quoteFor === S.crop + "|" + JSON.stringify(D.loc) && Q)) return;
    loading = true; failed = false; Q = null; quoteFor = S.crop + "|" + JSON.stringify(D.loc);
    fetch("/rates/quote/?crop=" + encodeURIComponent(S.crop), { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (q) {
      Q = q; loading = false;
      if (q.typical && !n(S.rate)) { S.rate = String(q.typical); S.rateUnit = "quintal"; S.rateLabel = "typical"; save(); }
      render();
    }).catch(function () { loading = false; failed = true; render(); });
  }

  function setField(name, value) { S[name] = String(value); save(); }
  function refreshNext() { var b = $("next"); if (!b) return; var bad = S.step === "qty" ? !n(S.qty) : S.step === "rate" ? !n(S.rate) : false; b.disabled = bad; }

  wiz.addEventListener("click", function (e) {
    var el = e.target.closest("[data-act]"); if (!el) return;
    var act = el.dataset.act, v = el.dataset.v;
    if (act === "crop") { if (S.crop !== v) { S.rate = ""; S.rateLabel = ""; S.directRate = ""; S.directLabel = ""; Q = null; } S.crop = v; save(); go("qty"); }
    else if (act === "unit") { S.unit = v; save(); render(); }
    else if (act === "inc" || act === "dec") { var cur = n(S.qty) + (act === "inc" ? 1 : -1) * QTY_STEP[S.unit]; setField("qty", Math.max(0, Math.round(cur * 100) / 100) || ""); render(); }
    else if (act === "chip") { var f = el.dataset.f; setField(f, v); if (f === "qty") S.qty = String(v); render(); }
    else if (act === "rate") { S.rate = v; S.rateUnit = "quintal"; S.rateLabel = el.dataset.k; save(); render(); }
    else if (act === "rateunit") { S.rateUnit = S.rateUnit === "kg" ? "quintal" : "kg"; save(); render(); }
    else if (act === "direct") { S.directRate = v; S.directLabel = el.dataset.l; save(); render(); }
    else if (act === "next") { var i = STEPS.indexOf(S.step); go(STEPS[Math.min(STEPS.length - 1, i + 1)]); }
    else if (act === "back") { var j = STEPS.indexOf(S.step); go(STEPS[Math.max(0, j - 1)]); }
    else if (act === "restart") { S = Object.assign({}, blank); Q = null; quoteFor = ""; save(); render(); }
    else if (act === "speak") speak();
    else if (act === "send") send(el.dataset.ch);
    else if (act === "alert") alertMe(el.dataset.ch);
  });

  wiz.addEventListener("input", function (e) {
    var t = e.target;
    if (t.id === "crop-search") { var q = t.value.trim().toLowerCase(); wiz.querySelectorAll(".tile").forEach(function (b) { b.hidden = !!q && b.dataset.name.indexOf(q) < 0; }); return; }
    if (t.id === "qty") setField("qty", t.value.replace(",", "."));
    else if (t.id === "bagkg") setField("bagKg", t.value.replace(",", "."));
    else if (t.id === "own-rate") { setField("rate", t.value.replace(",", ".")); S.rateLabel = "own"; save(); }
    else if (t.id === "direct-rate") { setField("directRate", t.value.replace(",", ".")); S.directLabel = "own"; save(); }
    else if (t.dataset.f) setField(t.dataset.f, t.value.replace(",", "."));
    refreshNext();
  });
  wiz.addEventListener("change", function (e) { if (e.target.id === "direct-rate") render(); });

  /* ---------- result actions ---------- */
  function speak() {
    if (window.sbVoice) { window.sbVoice.say(summary()); return; }
    try {
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(summary()); u.lang = D.speech; u.rate = 0.9; speechSynthesis.speak(u);
    } catch (e) {}
  }
  function csrf() { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  function postJSON(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(body) }).then(function (r) { return r.json(); });
  }
  function send(channel) {
    postJSON("/calculator/send/", { channel: channel, inputs: Object.assign({ crop: S.crop }, S) }).then(function (d) {
      if (d.delivered) toast(channel === "whatsapp" ? T("Sent to your WhatsApp.") : T("Sent as SMS to your phone."));
      else if (d.ok) { toast(T("Messages are not switched on yet. WhatsApp will open so you can send it to yourself.")); window.open(channel === "sms" ? d.sms_url : d.wa_url, "_blank"); }
      else toast(d.error === "daily_limit" || d.status === "blocked" ? T("Too many messages today. Try tomorrow.") : T("Something went wrong. Please try again."));
    }).catch(function () { toast(T("Something went wrong. Please try again.")); });
  }
  function alertMe(channel) {
    postJSON("/rates/alert/", { crop: S.crop, channel: channel }).then(function (d) {
      toast(d.ok ? (d.live ? T("You will get {crop} rates every day.", { crop: cropOf(S.crop).label }) : T("Saved. Daily messages start as soon as messaging is switched on.")) : T("Something went wrong. Please try again."));
    }).catch(function () { toast(T("Something went wrong. Please try again.")); });
  }

  /* ---------- start ---------- */
  if (window.SBLoc) SBLoc.onChange(function (res) {
    D.loc = { state: res.state, district: res.district }; Q = null; quoteFor = ""; S.rate = S.rateLabel === "own" ? S.rate : ""; save();
    fetch("/rates/summary/", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      var by = {}; d.crops.forEach(function (c) { by[c.crop] = c.typical; });
      D.crops.forEach(function (c) { c.typical = by[c.crop] || null; });
      render();
    });
  });
  var p = D.preset || {};
  if (p.crop && D.crops.some(function (c) { return c.crop === p.crop; })) {
    S.crop = p.crop; if (p.qty) S.qty = p.qty; if (["quintal", "kg", "tonne", "bag"].indexOf(p.unit) >= 0) S.unit = p.unit;
    S.rate = ""; S.rateLabel = ""; S.step = n(S.qty) ? "rate" : "qty"; save();
  }
  if (S.step !== "crop" && !S.crop) S.step = "crop";
  render();
})(typeof window !== "undefined" ? window : globalThis);
