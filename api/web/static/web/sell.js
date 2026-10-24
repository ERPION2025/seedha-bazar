/* Listing form: shows how much of the book's stock is free in the unit chosen, fills it in on request, warns when over. */
(function () {
  var box = document.getElementById("stockbox");
  if (!box) return;
  var freeKg = parseFloat(box.getAttribute("data-free-kg")) || 0;
  var qty = document.getElementById("id_quantity"), unit = document.getElementById("id_unit"), bag = document.getElementById("id_bag_weight_kg");
  var over = document.getElementById("over"), all = document.getElementById("sell-all");
  var PER = { kg: 1, quintal: 100, tonne: 1000 };
  function per() {
    if (!unit) return 100;
    if (unit.value === "bag") { var b = parseFloat(bag && bag.value); return b > 0 ? b : 0; }
    return PER[unit.value] || 100;
  }
  function freeInUnit() { var p = per(); return p ? Math.floor(freeKg / p * 1000) / 1000 : 0; } // rounded down: never above the stock
  function check() {
    var q = parseFloat(qty && qty.value), p = per();
    over.hidden = !(p && q > 0 && q * p > freeKg + 1e-6);
  }
  all.addEventListener("click", function () {
    if (per()) { qty.value = freeInUnit(); check(); qty.focus(); }
    else if (bag) bag.focus();
  });
  [qty, unit, bag].forEach(function (e) { if (e) e.addEventListener("input", check); });
  check();
})();
