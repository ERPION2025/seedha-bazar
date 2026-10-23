/* In-app video: a thumbnail until tapped, then the (privacy-friendly) player. Nothing downloads before the tap. */
(function () {
  document.addEventListener("click", function (e) {
    var b = e.target.closest(".vid");
    if (!b) return;
    var f = document.createElement("iframe");
    f.src = b.getAttribute("data-embed");
    f.title = b.getAttribute("data-title") || "";
    f.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    f.setAttribute("allowfullscreen", "");
    f.className = "vidframe";
    b.replaceWith(f);
  });
  var q = (location.search.match(/[?&]play=(\d+)/) || [])[1];
  if (q) { var t = document.querySelector('[data-pk="' + q + '"] .vid'); if (t) t.click(); }
})();
