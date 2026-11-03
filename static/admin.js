(function () {
  var all = document.getElementById("selall");
  var btn = document.getElementById("delsel");
  var cnt = document.getElementById("selcount");
  var form = document.getElementById("bulkform");
  var boxes = Array.prototype.slice.call(document.querySelectorAll(".rowpick"));
  if (!all || !btn) return;
  function sync() {
    var n = boxes.filter(function (b) { return b.checked; }).length;
    cnt.textContent = n;
    btn.disabled = n === 0;
    all.checked = n > 0 && n === boxes.length;
    all.indeterminate = n > 0 && n < boxes.length;
  }
  all.addEventListener("change", function () {
    boxes.forEach(function (b) { b.checked = all.checked; });
    sync();
  });
  boxes.forEach(function (b) { b.addEventListener("change", sync); });
  form.addEventListener("submit", function (e) {
    var n = boxes.filter(function (b) { return b.checked; }).length;
    if (!n || !window.confirm(n + " Response(s)-ஐ நிரந்தரமா நீக்கணுமா?")) e.preventDefault();
  });
  sync();
})();