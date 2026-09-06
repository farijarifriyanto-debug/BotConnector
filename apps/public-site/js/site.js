(function () {
  "use strict";

  document.querySelectorAll(".mobile-menu").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.body.classList.toggle("menu-open");
    });
  });

  // Dropdown nav groups: click-toggle on touch/mobile, hover handles desktop via CSS.
  document.querySelectorAll(".has-dd > .dd-trigger").forEach(function (trigger) {
    trigger.addEventListener("click", function (e) {
      e.preventDefault();
      var parent = trigger.closest(".has-dd");
      var wasOpen = parent.classList.contains("dd-open");
      document.querySelectorAll(".has-dd.dd-open").forEach(function (el) {
        el.classList.remove("dd-open");
      });
      if (!wasOpen) parent.classList.add("dd-open");
    });
  });

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".has-dd")) {
      document.querySelectorAll(".has-dd.dd-open").forEach(function (el) {
        el.classList.remove("dd-open");
      });
    }
  });
})();
