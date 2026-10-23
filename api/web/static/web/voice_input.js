/* Speak instead of typing, and record voice notes. Free: uses the phone's own browser features, no keys.
   - Any <textarea data-voice> or <input data-voice> gets a 🎤 button: speech becomes text (Web Speech API).
   - A [data-record] button records up to 60 s with the microphone into the form's [data-record-input] file field.
   Speech-to-text in Chrome is done by Google's speech service; the page says so before the first use. */
(function () {
  "use strict";
  var cfgNode = document.getElementById("sb-voice");
  var C = cfgNode ? JSON.parse(cfgNode.textContent) : { speech: "hi-IN", t: {} };
  var T = function (s) { return (C.t && C.t[s]) || s; };
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var NOTICE = "sbv_stt_ok";
  function noticed() { try { return localStorage.getItem(NOTICE) === "1"; } catch (e) { return false; } }
  function remember() { try { localStorage.setItem(NOTICE, "1"); } catch (e) {} }

  document.querySelectorAll("textarea[data-voice], input[data-voice]").forEach(function (field) {
    if (!SR) return;
    var b = document.createElement("button");
    b.type = "button"; b.className = "btn small ghost mic"; b.textContent = "🎤 " + T("Speak");
    b.setAttribute("aria-label", T("Speak instead of typing"));
    field.insertAdjacentElement("afterend", b);
    var rec = null, on = false;
    b.addEventListener("click", function () {
      if (on && rec) { rec.stop(); return; }
      if (!noticed()) {
        if (!window.confirm || !window.confirm(T("Your speech will be turned into text by your phone's browser (Chrome uses Google's speech service). Only the text is saved. Continue?"))) {
          if (window.confirm) return;
        }
        remember();
      }
      rec = new SR(); rec.lang = C.speech || "hi-IN"; rec.interimResults = true; rec.continuous = true;
      var base = field.value ? field.value.replace(/\s*$/, " ") : "";
      rec.onresult = function (e) {
        var text = "";
        for (var i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
        field.value = base + text;
        var form = field.form; if (form && form.via_voice) form.via_voice.value = "1";
      };
      rec.onend = function () { on = false; b.textContent = "🎤 " + T("Speak"); b.classList.remove("live"); };
      rec.onerror = function () { on = false; b.textContent = "🎤 " + T("Speak"); b.classList.remove("live"); };
      rec.start(); on = true; b.textContent = "⏹ " + T("Stop"); b.classList.add("live");
    });
  });

  document.querySelectorAll("[data-record]").forEach(function (btn) {
    var form = btn.closest("form"), input = form && form.querySelector("[data-record-input]"), status = form && form.querySelector("[data-record-status]");
    if (!input) return;
    if (!(navigator.mediaDevices && window.MediaRecorder)) { input.hidden = false; btn.hidden = true; return; } // fall back to picking a file
    var mr = null, chunks = [], timer = null;
    btn.addEventListener("click", function () {
      if (mr && mr.state === "recording") { mr.stop(); return; }
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        chunks = []; mr = new MediaRecorder(stream);
        mr.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
        mr.onstop = function () {
          clearTimeout(timer); stream.getTracks().forEach(function (t) { t.stop(); });
          var type = mr.mimeType || "audio/webm", blob = new Blob(chunks, { type: type });
          try {
            var dt = new DataTransfer(); dt.items.add(new File([blob], "voice." + (type.indexOf("ogg") >= 0 ? "ogg" : type.indexOf("mp4") >= 0 ? "m4a" : "webm"), { type: type }));
            input.files = dt.files;
            if (status) status.textContent = "✔ " + T("Voice note ready") + " (" + Math.round(blob.size / 1024) + " KB)";
          } catch (e) { input.hidden = false; if (status) status.textContent = T("Choose the recording file below"); }
          btn.textContent = "🎙️ " + T("Record again"); btn.classList.remove("live");
        };
        mr.start(); btn.textContent = "⏹ " + T("Stop recording"); btn.classList.add("live");
        if (status) status.textContent = T("Recording...");
        timer = setTimeout(function () { if (mr.state === "recording") mr.stop(); }, 60000);
      }).catch(function () { if (status) status.textContent = T("Microphone is blocked. Allow it in the browser settings."); input.hidden = false; });
    });
  });

  document.querySelectorAll("[data-share-location]").forEach(function (box) {
    box.addEventListener("change", function () {
      var form = box.closest("form");
      if (!box.checked) { form.lat.value = ""; form.lon.value = ""; return; }
      if (!navigator.geolocation) return;
      navigator.geolocation.getCurrentPosition(function (p) { form.lat.value = p.coords.latitude.toFixed(5); form.lon.value = p.coords.longitude.toFixed(5); },
        function () { box.checked = false; }, { enableHighAccuracy: true, timeout: 15000 });
    });
  });
})();
