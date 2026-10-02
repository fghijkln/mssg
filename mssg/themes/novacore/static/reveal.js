/* 滚动显现：元素进入视口时从 data-reveal 指定方向滑入。
   用法：<div data-reveal="up|down|left|right|zoom" data-delay="1|2|3">…</div>
   纯原生，无依赖。 */
(function () {
  "use strict";
  function init() {
    if (!("IntersectionObserver" in window)) {
      document.querySelectorAll("[data-reveal]").forEach(function (el) {
        el.classList.add("in");
      });
      return;
    }
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }
    );
    document.querySelectorAll("[data-reveal]").forEach(function (el) {
      el.classList.add("rv");
      io.observe(el);
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
