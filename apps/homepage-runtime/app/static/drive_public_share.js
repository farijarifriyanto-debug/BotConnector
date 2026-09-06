(() => {
  "use strict";

  async function copyText(value) {
    if (
      navigator.clipboard
      && window.isSecureContext
    ) {
      await navigator.clipboard.writeText(value);
      return;
    }

    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";

    document.body.appendChild(area);
    area.select();

    document.execCommand("copy");

    document.body.removeChild(area);
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest(
      "[data-copy-target]"
    );

    if (!button) {
      return;
    }

    const id = button.getAttribute(
      "data-copy-target"
    );

    const input = document.getElementById(id);

    if (!input) {
      return;
    }

    const original = button.textContent;

    try {
      await copyText(input.value);

      button.textContent = "Tersalin";

      window.setTimeout(() => {
        button.textContent = original;
      }, 1800);

    } catch (_error) {
      input.focus();
      input.select();

      button.textContent = "Pilih lalu salin";
    }
  });
})();
