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


  document.addEventListener(
    "click",
    async (event) => {

      const button = event.target.closest(
        "[data-copy]"
      );

      if (!button) {
        return;
      }

      const id = button.getAttribute(
        "data-copy"
      );

      const input = document.getElementById(
        id
      );

      if (!input) {
        return;
      }

      const original = button.textContent;

      try {

        await copyText(
          input.value
        );

        button.textContent = "Tersalin";

        window.setTimeout(
          () => {
            button.textContent = original;
          },
          1800
        );

      } catch (_error) {

        input.focus();
        input.select();

        button.textContent = "Pilih lalu salin";
      }
    }
  );


  const file = document.getElementById(
    "fr-file"
  );

  const filename = document.getElementById(
    "fr-file-name"
  );


  if (
    file
    && filename
  ) {

    file.addEventListener(
      "change",
      () => {

        const selected = (
          file.files
          && file.files.length
          ? file.files[0]
          : null
        );

        filename.textContent = (
          selected
          ? selected.name
          : "Ketuk untuk memilih file dari perangkat Anda"
        );
      }
    );
  }


  const uploadForm = document.querySelector(
    ".fr-upload-form"
  );

  const uploadButton = document.getElementById(
    "fr-upload-button"
  );


  if (
    uploadForm
    && uploadButton
  ) {

    uploadForm.addEventListener(
      "submit",
      () => {

        uploadButton.disabled = true;
        uploadButton.textContent = "Mengirim file…";
      }
    );
  }

})();
