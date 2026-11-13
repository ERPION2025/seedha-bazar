/* The Seedha Bazar sound: a soft breeze through the crops, played quietly when a notification arrives and when
   something the person did has worked (a saved entry, a placed order, a sent notice...). Never loud, never repeated
   within a few seconds, and off when the person has switched it off in Notifications, Settings. */
(function () {
  "use strict";
  var b = document.body, url = b.getAttribute("data-sound"), on = b.getAttribute("data-sound-on") === "1", last = 0, audio = null;
  function play() {
    if (!on || !url || document.visibilityState === "hidden" || Date.now() - last < 4000) return;
    last = Date.now();
    try {
      audio = audio || new Audio(url);
      audio.volume = 0.3;
      audio.currentTime = 0;
      var p = audio.play();
      if (p && p.catch) p.catch(function () {});  // a browser that has not been tapped yet stays silent
    } catch (e) {}
  }
  window.SBSound = { play: play };
  if (document.querySelector(".msgs li.success")) play();  // the page says something just worked
})();
