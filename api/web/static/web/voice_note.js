/* Speak: records with MediaRecorder (kept only if the person agreed) and turns speech into text with the browser's speech
   service in the chosen language, then saves both. Works best in Chrome on Android. */
(function () {
  "use strict";
  var box = document.getElementById("voice-box"); if (!box) return;
  var btn = document.getElementById("vrec"), out = document.getElementById("vtext"), st = document.getElementById("vstatus"), sel = document.getElementById("vlang");
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition, keep = box.getAttribute("data-keep") === "1";
  var cfg = JSON.parse((document.getElementById("sb-voice") || { textContent: "{\"t\":{}}" }).textContent), T = function (s) { return (cfg.t && cfg.t[s]) || s; };
  var csrf = function () { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; };
  var rec = null, mr = null, chunks = [], text = "", stream = null, on = false, label = btn.textContent;

  function finish() {
    on = false; btn.textContent = label; btn.classList.remove("live");
    var send = function (blob) {
      var fd = new FormData(); fd.append("language", sel.value); fd.append("text", text.trim());
      if (blob && keep) fd.append("audio", blob, "voice.webm");
      if (!text.trim() && !blob) { st.textContent = "✖"; return; }
      st.textContent = T("Saving...");
      fetch("/voice/save/", { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf() }, body: fd })
        .then(function (r) { return r.json(); }).then(function () { location.reload(); });
    };
    if (mr && mr.state === "recording") { mr.onstop = function () { stream && stream.getTracks().forEach(function (t) { t.stop(); }); send(new Blob(chunks, { type: mr.mimeType || "audio/webm" })); }; mr.stop(); }
    else send(null);
  }

  btn.addEventListener("click", function () {
    if (on) { if (rec) rec.stop(); else finish(); return; }
    text = ""; out.textContent = ""; on = true; btn.textContent = "⏹ " + T("Stop recording"); btn.classList.add("live");
    var startRecorder = (navigator.mediaDevices && window.MediaRecorder) ? navigator.mediaDevices.getUserMedia({ audio: true }).then(function (s) {
      stream = s; chunks = []; mr = new MediaRecorder(s); mr.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); }; mr.start();
      setTimeout(function () { if (on) (rec ? rec.stop() : finish()); }, 60000);
    }) : Promise.resolve();
    startRecorder.catch(function () { st.textContent = T("Microphone is blocked. Allow it in the browser settings."); }).then(function () {
      if (!SR) { st.textContent = T("Recording..."); return; }
      rec = new SR(); rec.lang = sel.value; rec.interimResults = true; rec.continuous = true;
      rec.onresult = function (e) { var s = ""; for (var i = 0; i < e.results.length; i++) s += e.results[i][0].transcript; text = s; out.textContent = s; };
      rec.onend = function () { rec = null; finish(); };
      rec.onerror = function () { };
      rec.start(); st.textContent = T("Listening...");
    });
  });
})();
