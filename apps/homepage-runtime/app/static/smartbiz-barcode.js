/* SMARTBIZ_BARCODE_UI_V061 */

(() => {
  "use strict";

  const normalize = (value) => String(value ?? "").trim();

  const decimalValue = (value) => {
    const normalized = normalize(value).replace(",", ".");
    const parsed = Number(normalized);

    return Number.isFinite(parsed) ? parsed : 0;
  };

  const dispatchValue = (element) => {
    element.dispatchEvent(
      new Event("input", {
        bubbles: true,
      })
    );

    element.dispatchEvent(
      new Event("change", {
        bubbles: true,
      })
    );
  };

  const findBarcodeOption = (select, barcode) => {
    const code = normalize(barcode);

    return Array.from(select.options).find(
      (option) =>
        normalize(option.dataset.barcode) === code
    );
  };

  const ensureCartRow = (form) => {
    const container = form.querySelector(
      "[data-order-items]"
    );

    if (!container) {
      return null;
    }

    const rows = Array.from(
      container.querySelectorAll(".sbo-item-row")
    );

    const emptyRow = rows.find((row) => {
      const select = row.querySelector(
        'select[name="product_id"]'
      );

      return select && !select.value;
    });

    if (emptyRow) {
      return emptyRow;
    }

    const source = rows[rows.length - 1];

    if (!source) {
      return null;
    }

    const clone = source.cloneNode(true);
    const select = clone.querySelector(
      'select[name="product_id"]'
    );

    const quantity = clone.querySelector(
      'input[name="quantity"]'
    );

    if (select) {
      select.value = "";
      select.removeAttribute("required");
    }

    if (quantity) {
      quantity.value = "";
      quantity.removeAttribute("required");
    }

    container.appendChild(clone);

    return clone;
  };

  const applyFill = (trigger, barcode) => {
    const target = document.querySelector(
      trigger.dataset.target || ""
    );

    if (!target) {
      return {
        ok: false,
        message: "Kolom barcode tidak ditemukan.",
      };
    }

    target.value = barcode;
    dispatchValue(target);
    target.focus();

    return {
      ok: true,
      message: `Barcode ${barcode} berhasil dibaca.`,
    };
  };

  const applySelect = (trigger, barcode) => {
    const select = document.querySelector(
      trigger.dataset.target || ""
    );

    if (!select) {
      return {
        ok: false,
        message: "Pilihan produk tidak ditemukan.",
      };
    }

    const option = findBarcodeOption(
      select,
      barcode
    );

    if (!option) {
      return {
        ok: false,
        message: (
          `Barcode ${barcode} belum terdaftar. ` +
          "Daftarkan barcode pada halaman Dashboard."
        ),
      };
    }

    select.value = option.value;
    dispatchValue(select);

    const focusTarget = document.querySelector(
      trigger.dataset.focus || ""
    );

    if (focusTarget) {
      focusTarget.focus();
    }

    return {
      ok: true,
      message: `${option.textContent.trim()} dipilih.`,
    };
  };

  const applyCart = (trigger, barcode) => {
    const form = document.querySelector(
      trigger.dataset.form || ""
    );

    if (!form) {
      return {
        ok: false,
        message: "Form pesanan tidak ditemukan.",
      };
    }

    const selects = Array.from(
      form.querySelectorAll(
        'select[name="product_id"]'
      )
    );

    let matchingOption = null;

    for (const select of selects) {
      const option = findBarcodeOption(
        select,
        barcode
      );

      if (option) {
        matchingOption = option;
        break;
      }
    }

    if (!matchingOption) {
      return {
        ok: false,
        message: (
          `Barcode ${barcode} belum terdaftar. ` +
          "Daftarkan barcode pada halaman Dashboard."
        ),
      };
    }

    let row = selects
      .map((select) =>
        select.closest(".sbo-item-row")
      )
      .find((candidate) => {
        if (!candidate) {
          return false;
        }

        const select = candidate.querySelector(
          'select[name="product_id"]'
        );

        return (
          select &&
          select.value === matchingOption.value
        );
      });

    if (!row) {
      row = ensureCartRow(form);

      if (!row) {
        return {
          ok: false,
          message: (
            "Baris produk baru tidak dapat dibuat."
          ),
        };
      }

      const select = row.querySelector(
        'select[name="product_id"]'
      );

      if (!select) {
        return {
          ok: false,
          message: (
            "Pilihan produk pada baris baru tidak ditemukan."
          ),
        };
      }

      select.value = matchingOption.value;
      dispatchValue(select);
    }

    const quantity = row.querySelector(
      'input[name="quantity"]'
    );

    if (!quantity) {
      return {
        ok: false,
        message: "Kolom jumlah tidak ditemukan.",
      };
    }

    quantity.value = String(
      decimalValue(quantity.value) + 1
    );

    dispatchValue(quantity);
    quantity.focus();

    return {
      ok: true,
      message: (
        `${matchingOption.textContent.trim()} ` +
        `ditambahkan. Jumlah sekarang ${quantity.value}.`
      ),
    };
  };

  const applyBarcode = (trigger, barcode) => {
    const code = normalize(barcode);

    if (!code) {
      return {
        ok: false,
        message: "Barcode masih kosong.",
      };
    }

    switch (trigger.dataset.mode) {
      case "fill":
        return applyFill(trigger, code);

      case "select":
        return applySelect(trigger, code);

      case "cart":
        return applyCart(trigger, code);

      default:
        return {
          ok: false,
          message: "Mode scanner tidak dikenali.",
        };
    }
  };

  const initialize = () => {
    const modal = document.querySelector(
      "[data-barcode-modal]"
    );

    const video = modal?.querySelector(
      "[data-barcode-video]"
    );

    const status = modal?.querySelector(
      "[data-barcode-status]"
    );

    const closeButton = modal?.querySelector(
      "[data-barcode-close]"
    );

    let controls = null;
    let activeTrigger = null;
    let lastCode = "";
    let lastReadAt = 0;

    const setStatus = (message) => {
      if (status) {
        status.textContent = message;
      }
    };

    const stopCamera = () => {
      try {
        controls?.stop();
      } catch (_) {
        // Tidak menggagalkan UI.
      }

      controls = null;

      if (video?.srcObject) {
        for (const track of video.srcObject.getTracks()) {
          track.stop();
        }

        video.srcObject = null;
      }
    };

    const closeScanner = () => {
      stopCamera();

      if (modal) {
        modal.hidden = true;
      }

      activeTrigger = null;
    };

    const openScanner = async (trigger) => {
      if (!modal || !video || !status) {
        return;
      }

      activeTrigger = trigger;
      modal.hidden = false;

      setStatus("Meminta izin kamera...");

      if (!window.isSecureContext) {
        setStatus(
          "Kamera hanya tersedia melalui HTTPS."
        );
        return;
      }

      if (
        !window.ZXingBrowser ||
        !window.ZXingBrowser.BrowserMultiFormatReader
      ) {
        setStatus(
          "Mesin scanner belum termuat. " +
          "Gunakan scanner USB atau input manual."
        );
        return;
      }

      try {
        const reader =
          new window.ZXingBrowser.BrowserMultiFormatReader();

        controls = await reader.decodeFromConstraints(
          {
            audio: false,
            video: {
              facingMode: {
                ideal: "environment",
              },
              width: {
                ideal: 1280,
              },
              height: {
                ideal: 720,
              },
            },
          },
          video,
          (result) => {
            if (!result || !activeTrigger) {
              return;
            }

            const code = normalize(
              result.getText()
            );

            const now = Date.now();

            if (
              code === lastCode &&
              now - lastReadAt < 1400
            ) {
              return;
            }

            lastCode = code;
            lastReadAt = now;

            const applied = applyBarcode(
              activeTrigger,
              code
            );

            setStatus(applied.message);

            if (applied.ok) {
              navigator.vibrate?.(80);

              window.setTimeout(
                closeScanner,
                350
              );
            }
          }
        );

        setStatus(
          "Arahkan kamera ke barcode dan tahan stabil."
        );

      } catch (error) {
        setStatus(
          "Kamera tidak dapat dibuka. " +
          "Izinkan kamera atau gunakan scanner USB."
        );

        console.error(
          "SmartBiz barcode camera:",
          error
        );
      }
    };

    document.addEventListener(
      "click",
      (event) => {
        const cameraTrigger =
          event.target.closest(
            "[data-barcode-camera]"
          );

        if (cameraTrigger) {
          event.preventDefault();
          openScanner(cameraTrigger);
          return;
        }

        const useTrigger =
          event.target.closest(
            "[data-barcode-use]"
          );

        if (!useTrigger) {
          return;
        }

        event.preventDefault();

        const input = document.querySelector(
          useTrigger.dataset.input || ""
        );

        if (!input) {
          return;
        }

        const applied = applyBarcode(
          useTrigger,
          input.value
        );

        const messageTarget =
          document.querySelector(
            useTrigger.dataset.message || ""
          );

        if (messageTarget) {
          messageTarget.textContent =
            applied.message;
        }

        if (applied.ok) {
          input.value = "";
          navigator.vibrate?.(50);
        }
      }
    );

    document.addEventListener(
      "keydown",
      (event) => {
        const input = event.target.closest(
          "[data-barcode-entry]"
        );

        if (!input || event.key !== "Enter") {
          return;
        }

        event.preventDefault();

        const useTrigger =
          document.querySelector(
            input.dataset.use || ""
          );

        useTrigger?.click();
      }
    );

    closeButton?.addEventListener(
      "click",
      closeScanner
    );

    modal?.addEventListener(
      "click",
      (event) => {
        if (event.target === modal) {
          closeScanner();
        }
      }
    );

    document.addEventListener(
      "keydown",
      (event) => {
        if (
          event.key === "Escape" &&
          modal &&
          !modal.hidden
        ) {
          closeScanner();
        }
      }
    );

    window.addEventListener(
      "pagehide",
      stopCamera
    );
  };

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      initialize,
      {
        once: true,
      }
    );
  } else {
    initialize();
  }
})();
