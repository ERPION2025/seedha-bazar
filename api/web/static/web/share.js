/* Share as a free ad. Draws a 1080x1080 branded picture on the phone (Hindi and Marathi render correctly here),
   uploads it so link previews show it, then opens the phone's share sheet (WhatsApp, Facebook, Instagram...) with the
   picture and a link. Where the share sheet cannot take pictures, it offers WhatsApp, Facebook and a download. */
(function () {
  "use strict";
  var csrf = function () { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; };

  function wrap(ctx, text, x, y, maxW, lh, maxLines) {
    var words = String(text).split(" "), line = "", n = 0;
    for (var i = 0; i < words.length; i++) {
      var test = line ? line + " " + words[i] : words[i];
      if (ctx.measureText(test).width > maxW && line) { ctx.fillText(line, x, y); y += lh; line = words[i]; if (++n >= maxLines - 1) break; }
      else line = test;
    }
    ctx.fillText(line, x, y);
    return y + lh;
  }

  function draw(d) {
    var c = document.createElement("canvas"); c.width = c.height = 1080;
    var x = c.getContext("2d"), font = '"Noto Sans Devanagari","Mukta",system-ui,sans-serif';
    var g = x.createLinearGradient(0, 0, 1080, 1080); g.addColorStop(0, "#14532d"); g.addColorStop(1, "#1f7a3f");
    x.fillStyle = g; x.fillRect(0, 0, 1080, 1080);
    x.fillStyle = "#f59e0b"; x.beginPath(); x.arc(980, 100, 220, 0, Math.PI * 2); x.fill();          // sun
    x.fillStyle = "#fbf9f4"; x.beginPath(); x.roundRect ? x.roundRect(60, 230, 960, 640, 40) : x.rect(60, 230, 960, 640); x.fill();
    x.fillStyle = "#fff"; x.font = "bold 64px " + font; x.textBaseline = "top"; x.fillText(d.brand, 70, 70);
    x.font = "34px " + font; x.fillStyle = "#e8f5ec"; x.fillText(d.tagline, 72, 150);
    x.font = "150px " + font; x.fillStyle = "#000"; x.fillText(d.emoji, 100, 270);
    x.fillStyle = "#14532d"; x.font = "bold 76px " + font; var y = wrap(x, d.title, 290, 300, 690, 88, 2);
    x.fillStyle = "#1c1917"; x.font = "44px " + font; y = Math.max(y, 470);
    d.lines.forEach(function (l) { y = wrap(x, l, 100, y, 880, 58, 2) + 6; });
    x.fillStyle = "#f59e0b"; x.beginPath(); x.roundRect ? x.roundRect(60, 900, 960, 130, 30) : x.rect(60, 900, 960, 130); x.fill();
    x.fillStyle = "#000"; x.font = "bold 44px " + font; wrap(x, d.cta, 100, 918, 880, 52, 1);
    x.font = "34px " + font; x.fillText(d.url.replace(/^https?:\/\//, ""), 100, 978);
    return c;
  }

  function sheet(d, blob) {
    var box = document.createElement("div"); box.className = "more-sheet"; box.innerHTML = "";
    var p = document.createElement("div"); p.className = "more-panel";
    var url = URL.createObjectURL(blob);
    p.innerHTML = '<div class="row between"><b>📣</b><button type="button" class="sbv-x" aria-label="✕">✕</button></div>' +
      '<img alt="" style="width:100%;max-width:420px;border-radius:14px;display:block;margin:10px auto" src="' + url + '">' +
      '<div class="more-grid">' +
      '<a target="_blank" rel="noopener" href="https://wa.me/?text=' + encodeURIComponent(d.share_text) + '"><span class="ic">💬</span>WhatsApp</a>' +
      '<a target="_blank" rel="noopener" href="https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(d.url) + '"><span class="ic">📘</span>Facebook</a>' +
      '<a download="seedha-bazar-' + d.code + '.png" href="' + url + '"><span class="ic">📸</span>Instagram</a>' +
      "</div>";
    box.appendChild(p); document.body.appendChild(box);
    box.addEventListener("click", function (e) { if (e.target === box || e.target.classList.contains("sbv-x")) box.remove(); });
  }

  function share(btn) {
    btn.disabled = true;
    var body = new FormData(); body.append("kind", btn.getAttribute("data-kind")); body.append("ref", btn.getAttribute("data-ref") || "");
    fetch("/share/new/", { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf() }, body: body })
      .then(function (r) { if (!r.ok) throw new Error("card"); return r.json(); })
      .then(function (d) {
        return (document.fonts ? document.fonts.ready : Promise.resolve()).then(function () {
          var c = draw(d);
          return new Promise(function (res) { c.toBlob(res, "image/png"); }).then(function (blob) {
            var up = new FormData(); up.append("image", blob, d.code + ".png");
            fetch("/share/" + d.code + "/image/", { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf() }, body: up });
            var file = new File([blob], "seedha-bazar-" + d.code + ".png", { type: "image/png" });
            if (navigator.canShare && navigator.canShare({ files: [file] })) {
              return navigator.share({ files: [file], text: d.share_text, title: d.title }).catch(function () {});
            }
            sheet(d, blob);
          });
        });
      })
      .catch(function () { alert && alert("✖"); })
      .then(function () { btn.disabled = false; });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-share]");
    if (b) { e.preventDefault(); share(b); }
  });
})();
