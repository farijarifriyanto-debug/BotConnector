"""BC Bisnis Telegram real-channel long-polling runtime (owner-only pilot).

Dedicated to BC Bisnis; never touches trading Telegram services. Reads a
dedicated token from env (loaded by systemd EnvironmentFile). If no token:
this runtime exits cleanly (no crash loop). Before polling: getWebhookInfo;
if a webhook is configured, it is NOT deleted and the poller stops (logs a
blocker). All updates funnel through the canonical intake draft lifecycle.

Never logs or prints the token.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta

import os
import time
import logging

from . import telegram_intake as ti
from . import telegram_registry as reg
from . import intake as intake_mod
from . import low_stock
from . import reorder as reorder_mod
from . import procurement as proc_mod
from . import sales as sales_mod
from . import umkm as umkm_mod
from .bot_client import BotApiClient, TelegramError

log = logging.getLogger("bc.bisnis.telegram.poller")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
# Ensure httpx/httpcore do not leak bot token URLs at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TOKEN_ENV = "BC_BISNIS_TELEGRAM_BOT_TOKEN"
MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram Bot API download cap
ALLOWED_EXT = {".csv", ".xlsx", ".xlsm"}


def _token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def _resolve_business_name(business_id: int) -> str:
    from . import core
    biz = core.get_business(business_id)
    return (biz.get("name") or "") if biz else ""


# ============================================================ message handlers
def _handle_message(bot, update, ctx: reg.TelegramExecutionContext | None):
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = (msg.get("chat") or {}).get("id")
    user_id = (msg.get("from") or {}).get("id", 0)
    doc = msg.get("document")

    if text.startswith(("/start", "/startgroup")):
        # /start <token>, /start@bot <token>, /startgroup <token>, /startgroup@bot <token>
        parts = text.split()
        if len(parts) > 1:
            raw_token = parts[1].strip()
            chat = msg.get("chat") or {}
            chat_title = chat.get("title") or ""
            chat_type = chat.get("type") or "private"
            res = reg.resolve_destination_pairing(
                raw_token=raw_token,
                chat_id=chat_id,
                telegram_user_id=user_id,
                chat_title=chat_title,
                chat_type=chat_type,
            )
            if res.get("ok"):
                biz_name = _resolve_business_name(res["business_id"])
                if res.get("destination_type") == "GROUP":
                    bot.send_message(chat_id, f"✅ Grup Telegram '{chat_title}' berhasil terhubung dengan {biz_name}.")
                else:
                    bot.send_message(chat_id, f"✅ Akun Telegram terhubung dengan {biz_name}.")
            else:
                reason = {
                    "token_already_used": "Token pairing sudah pernah dipakai.",
                    "token_expired": "Token pairing kedaluwarsa. Buat kode pairing baru di Business Suite.",
                    "unknown_token": "Token pairing tidak dikenal.",
                }.get(res.get("error"), "Gagal menghubungkan.")
                bot.send_message(chat_id, "Tidak dapat menghubungkan. " + reason)
        else:
            if ctx and ctx.source_type == "BYOB_WEBHOOK":
                bot.send_message(
                    chat_id,
                    "Bot ini sudah terhubung ke BotConnector Business Suite.\n\n"
                    "Untuk menghubungkan chat ini sebagai tujuan notifikasi, "
                    "buat tautan pairing dari Business Suite → Integrasi → Telegram.",
                )
            else:
                bot.send_message(
                    chat_id,
                    "Silakan buka Business Suite lalu tekan 'Hubungkan Telegram' untuk token pairing.",
                )
        return

    if text in ("/help", "/help@"):
        bot.send_message(chat_id,
            "Bantuan Perintah Business Suite:\n\n"
            "/status - status koneksi & bisnis aktif\n"
            "/bisnis - ganti bisnis aktif\n"
            "/cabang - ganti cabang aktif\n"
            "/unpair - putuskan koneksi Telegram\n\n"
            "/barang SKU|Nama|Harga|Stok\n"
            "/barang SKU|Nama|Harga|Modal|Stok\n\n"
            "/barcode Barcode - cari barcode\n"
            "/barcode Barcode|SKU|Nama|Harga|Stok\n"
            "/barcode Barcode|SKU|Nama|Harga|Modal|Stok\n\n"
            "/stokminimum - lihat batas stok minimum\n"
            "/stokminimum SKU THRESHOLD - atur batas minimum\n"
            "/stokminimum SKU off - nonaktifkan batas minimum\n\n"
            "/stokrendah - lihat produk stok menipis\n\n"
            "/supplier - kelola supplier\n"
            "/supplier tambah KODE|NAMA\n"
            "/supplier ubah KODE|NAMA\n"
            "/supplier KODE off\n\n"
            "/restockconfig - konfigurasi restock SKU\n"
            "/restockconfig SKU KODE_SUPPLIER|LEAD_TIME|MOQ|TARGET_STOK\n"
            "/restockconfig SKU off\n\n"
            "/reorder - rekomendasi restock inventaris\n"
            "/reorder SKU - detail kalkulasi restock SKU\n\n"
            "/po - daftar purchase order\n"
            "/po NOMOR - detail purchase order\n"
            "/po buat SKU - buat draft PO dari rekomendasi\n"
            "/po buat KODE_SUPPLIER SKU:QTY - buat draft PO manual\n"
            "/po batal NOMOR - batalkan PO\n\n"
            "/terimapo NOMOR - terima barang dari PO\n"
            "/terimapo NOMOR SKU:QTY - terima barang sebagian\n\n"
            "/tagihan - daftar tagihan supplier\n"
            "/tagihan NOMOR - detail tagihan\n"
            "/tagihan buat NOMOR_PO - buat draft tagihan dari PO\n"
            "/tagihan posting NOMOR - posting tagihan ke Keuangan/Utang\n"
            "/tagihan batal NOMOR - batalkan draft tagihan\n\n"
            "/bayar NOMOR_TAGIHAN JUMLAH - bayar tagihan (Kas)\n"
            "/bayar NOMOR_TAGIHAN JUMLAH BANK - bayar tagihan (Bank)\n\n"
            "--- ORDER-TO-CASH (B2B / WHOLESALE) ---\n"
            "/pelanggan - kelola master pelanggan\n"
            "/pelanggan tambah KODE|NAMA - tambah pelanggan\n"
            "/pelanggan KODE - detail pelanggan & limit piutang\n\n"
            "/penawaran - daftar penawaran harga\n"
            "/penawaran buat KODE SKU:QTY - buat penawaran\n"
            "/penawaran terima NOMOR - setujui penawaran\n"
            "/penawaran konversi NOMOR - konversi penawaran ke SO\n\n"
            "/salesorder - daftar sales order\n"
            "/salesorder buat KODE SKU:QTY - buat sales order\n"
            "/salesorder konfirmasi NOMOR - konfirmasi sales order\n\n"
            "/kirimpesanan - daftar pesanan siap dikirim\n"
            "/kirimpesanan NOMOR_SO - catat pengiriman barang\n\n"
            "/invoice - daftar customer invoice\n"
            "/invoice buat NOMOR_SO - buat invoice dari barang terkirim\n"
            "/invoice posting NOMOR - posting invoice ke Piutang & Keuangan\n\n"
            "/piutang - laporan umur piutang (AR Aging)\n"
            "/piutang KODE - rincian piutang per pelanggan\n\n"
            "/terimabayar NOMOR_INVOICE JUMLAH - terima pembayaran piutang\n\n"
            "/returjual NOMOR_SO SKU:QTY - retur penjualan & nota kredit\n\n"
            "--- OPERASIONAL HARIAN UMKM ---\n"
            "/keluar JUMLAH|KETERANGAN|KATEGORI - catat pengeluaran (Kas)\n"
            "/keluar JUMLAH|KETERANGAN|KATEGORI|BANK - catat pengeluaran (Bank)\n\n"
            "/pengeluaran - pengeluaran hari ini\n"
            "/pengeluaran hariini - pengeluaran hari ini\n"
            "/pengeluaran bulanini - pengeluaran bulan ini\n"
            "/pengeluaran YYYY-MM - pengeluaran bulan tertentu\n\n"
            "/kas - saldo kas & bank saat ini\n\n"
            "/labarugi - laporan laba rugi bulan ini\n"
            "/labarugi YYYY-MM - laporan laba rugi bulan tertentu\n\n"
            "/ringkasan - ringkasan bisnis hari ini (all-in-one)\n\n"
            "/posisi - posisi keuangan (neraca sederhana)\n\n"
            "/export - export laporan keuangan CSV bulan ini\n"
            "/export YYYY-MM - export laporan keuangan CSV bulan tertentu\n\n"
            "Kirim file .csv/.xlsx untuk impor banyak produk.")
        return
    if text in ("/status", "/status@"):
        if not ctx or not ctx.available_businesses:
            bot.send_message(chat_id, "Belum terhubung. Buka Business Suite lalu tekan 'Hubungkan Telegram'.")
            return
        if len(ctx.available_businesses) == 1:
            bot.send_message(chat_id, f"Terhubung dengan *{ctx.business_name}* (Role: {ctx.role}, Cabang: {ctx.branch_name or 'Default'}).", parse_mode="Markdown")
        else:
            biz_list = "\n".join(f"• {b['name']}" for b in ctx.available_businesses)
            bot.send_message(chat_id, f"Terhubung ke {len(ctx.available_businesses)} bisnis:\n{biz_list}\n\nBisnis aktif saat ini: *{ctx.business_name}*\n(Ketik /bisnis untuk beralih)", parse_mode="Markdown")
        return

    if text in ("/bisnis", "/bisnis@"):
        if not ctx or not ctx.available_businesses:
            bot.send_message(chat_id, "Belum terhubung ke bisnis manapun.")
            return
        if len(ctx.available_businesses) == 1:
            bot.send_message(chat_id, f"Anda hanya terhubung ke 1 bisnis: *{ctx.business_name}*.", parse_mode="Markdown")
            return
        keyboard = [[{"text": ("▶ " if b["id"] == ctx.business_id else "") + b["name"], "callback_data": f"biz_switch:{b['id']}"}] for b in ctx.available_businesses]
        bot.send_message(chat_id, f"Bisnis aktif saat ini: *{ctx.business_name}*\n\nPilih bisnis untuk beralih:", reply_markup={"inline_keyboard": keyboard}, parse_mode="Markdown")
        return

    if text in ("/cabang", "/cabang@"):
        if not ctx or not ctx.business_id:
            bot.send_message(chat_id, "Belum terhubung ke bisnis.")
            return
        from . import core
        branches = core.list_branch(ctx.business_id)
        if not branches:
            bot.send_message(chat_id, f"Bisnis *{ctx.business_name}* belum memiliki data cabang.", parse_mode="Markdown")
            return
        if len(branches) == 1:
            bot.send_message(chat_id, f"Bisnis ini hanya memiliki 1 cabang: *{branches[0]['name']}*.", parse_mode="Markdown")
            return
        keyboard = [[{"text": ("▶ " if br["id"] == ctx.branch_id else "") + br["name"], "callback_data": f"br_switch:{br['id']}"}] for br in branches]
        bot.send_message(chat_id, f"Cabang aktif saat ini: *{ctx.branch_name or 'Default'}*\n\nPilih cabang:", reply_markup={"inline_keyboard": keyboard}, parse_mode="Markdown")
        return

    if text.startswith("/unpair"):
        if not ctx or not ctx.business_id:
            bot.send_message(chat_id, "Belum terhubung.")
            return
        ti.unpair(ctx.business_id)
        bot.send_message(chat_id, f"Koneksi Telegram untuk {ctx.business_name} dilepas.")
        return

    if not ctx or not ctx.available_businesses:
        bot.send_message(chat_id, "Belum terhubung. Buka Business Suite lalu tekan 'Hubungkan Telegram'.")
        return

    if ctx.business_id == 0:
        keyboard = [[{"text": b["name"], "callback_data": f"biz_switch:{b['id']}"}] for b in ctx.available_businesses]
        bot.send_message(chat_id, "Anda terhubung ke beberapa bisnis. Pilih bisnis aktif Anda terlebih dahulu:", reply_markup={"inline_keyboard": keyboard})
        return

    # Check permission for admin-only commands
    if text.startswith(("/supplier", "/restockconfig", "/po buat", "/po batal", "/tagihan buat", "/tagihan posting", "/tagihan batal", "/bayar", "/stokminimum")):
        if not ctx.is_admin:
            bot.send_message(chat_id, "⛔ Perintah ini memerlukan hak akses Owner/Admin di Business Suite.")
            return

    # Assign contextual variables for command handlers
    business_id = ctx.business_id
    owner_id = ctx.business_id
    branch_id = ctx.branch_id or 0
    warehouse_id = ctx.warehouse_id or 0
    biz_name = ctx.business_name

    if doc:
        file_id = doc.get("file_id")
        file_unique = doc.get("file_unique_id", "")
        fname = (doc.get("file_name") or "").lower()
        ext = os.path.splitext(fname)[1] if fname else ""
        if ext not in ALLOWED_EXT:
            bot.send_message(chat_id, "Format tidak didukung. Kirim .csv, .xlsx, atau .xlsm.")
            return
        try:
            f = bot.get_file(file_id)
            data = bot.download_file(f.get("file_path", ""))
        except TelegramError as e:
            bot.send_message(chat_id, f"Gagal mengunduh file: {e}")
            return
        if len(data) > MAX_FILE_BYTES:
            bot.send_message(chat_id, "File terlalu besar (maks 20 MB). Gunakan upload di BC Bisnis web/mobile.")
            return
        fmt = "XLSX" if ext in (".xlsx", ".xlsm") else "CSV"
        draft = ti.submit_intake_draft(
            business_id=business_id, telegram_user_id=user_id, owner_id=owner_id,
            format=fmt, filename=(doc.get("file_name") or "upload"), content=data,
            actor=f"tg:{user_id}")
        if not draft.get("ok"):
            bot.send_message(chat_id, "Gagal membaca file: " + str(draft.get("error", "")))
            return
        batch_id = draft["batch_id"]
        preview = ti.render_text_preview(batch_id, ready_rows=draft["ready_rows"],
                                         warning_rows=draft["warning_rows"])
        header = f"File: {doc.get('file_name') or 'upload'}"
        if preview.get("ok"):
            bot.send_message(chat_id,
                f"{header}\n\n{preview['message']}\n\nBelum ada perubahan stok/produk.",
                reply_markup={"inline_keyboard": [[
                    {"text": "Konfirmasi Import", "callback_data": f"confirm:{batch_id}"},
                    {"text": "Batalkan", "callback_data": f"cancel:{batch_id}"},
                ]]})
        else:
            bot.send_message(chat_id, f"{header}\n\n{preview['message']}")
        return

    if text.startswith("/barang"):
        rest = text[len("/barang"):].strip()
        if not rest:
            bot.send_message(chat_id,
                "Format: /barang SKU|Nama|Harga|Stok atau /barang SKU|Nama|Harga|Modal|Stok")
            return
        draft = ti.submit_text_product(
            business_id=business_id, telegram_id=user_id, owner_id=owner_id, text=rest)
        if not draft.get("ok"):
            usage = draft.get("usage") or "Format: /barang SKU|Nama|Harga|Stok atau /barang SKU|Nama|Harga|Modal|Stok"
            bot.send_message(chat_id, "Gagal membaca produk. " + usage)
            return
        batch_id = draft["batch_id"]
        if not draft["total_rows"]:
            bot.send_message(chat_id, "Tidak ada produk terbaca. Format: /barang SKU|Nama|Harga|Stok atau /barang SKU|Nama|Harga|Modal|Stok")
            return
        preview = ti.render_text_preview(batch_id, ready_rows=draft["ready_rows"],
                                         warning_rows=draft["warning_rows"])
        if preview.get("ok"):
            bot.send_message(chat_id, preview["message"],
                reply_markup={"inline_keyboard": [[
                    {"text": "Konfirmasi", "callback_data": f"confirm:{batch_id}"},
                    {"text": "Batal", "callback_data": f"cancel:{batch_id}"},
                ]]})
        else:
            bot.send_message(chat_id, preview["message"])
        return

    if text.startswith("/barcode"):
        rest = text[len("/barcode"):].strip()
        if not rest:
            bot.send_message(chat_id,
                "Format: /barcode Barcode|SKU|Nama|Harga|Stok atau /barcode Barcode|SKU|Nama|Harga|Modal|Stok")
            return
        # MODE A — lookup only: a single bare barcode value.
        if "|" not in rest and "," not in rest:
            from . import barcode as bc
            barcode_val = rest.strip()
            if not barcode_val:
                bot.send_message(chat_id, "Barcode kosong. Format: /barcode Barcode|SKU|Nama|Harga|Stok")
                return
            res = bc.lookup_barcode(business_id=business_id, barcode=barcode_val)
            if res.get("found"):
                bot.send_message(chat_id,
                    f"Barcode ditemukan.\n\nBarcode: {res.get('barcode')}\n"
                    f"SKU: {res.get('sku')}\nNama: {res.get('name')}")
            else:
                bot.send_message(chat_id,
                    "Barcode belum dikenal.\n\nUntuk menambah produk baru:\n"
                    "/barcode Barcode|SKU|Nama|Harga|Stok\n"
                    "atau\n/barcode Barcode|SKU|Nama|Harga|Modal|Stok")
            return
        # MODE B — unknown barcode product draft.
        draft = ti.submit_barcode_product(
            business_id=business_id, telegram_id=user_id, owner_id=owner_id, text=rest)
        if not draft.get("ok"):
            usage = draft.get("usage") or "Format: /barcode Barcode|SKU|Nama|Harga|Stok atau /barcode Barcode|SKU|Nama|Harga|Modal|Stok"
            bot.send_message(chat_id, "Gagal membaca barcode. " + usage)
            return
        batch_id = draft["batch_id"]
        if not draft["total_rows"]:
            bot.send_message(chat_id, "Tidak ada produk terbaca. Format: /barcode Barcode|SKU|Nama|Harga|Stok")
            return
        preview = ti.render_text_preview(batch_id, ready_rows=draft["ready_rows"],
                                         warning_rows=draft["warning_rows"])
        if preview.get("ok"):
            bot.send_message(chat_id, preview["message"],
                reply_markup={"inline_keyboard": [[
                    {"text": "Konfirmasi", "callback_data": f"confirm:{batch_id}"},
                    {"text": "Batal", "callback_data": f"cancel:{batch_id}"},
                ]]})
        else:
            bot.send_message(chat_id, preview["message"])
        return

    if text.startswith("/stokminimum"):
        rest = text[len("/stokminimum"):].strip()
        if not rest:
            items = low_stock.list_thresholds(business_id=business_id)
            if not items:
                bot.send_message(chat_id, "Belum ada batas stok minimum yang diatur.")
            else:
                lines = ["⚙️ BATAS STOK MINIMUM", ""]
                for item in items:
                    lines.append(f"• {item['product_name']}")
                    lines.append(f"  SKU: {item['sku']}")
                    lines.append(f"  Batas minimum: {item['threshold']}")
                    lines.append("")
                bot.send_message(chat_id, "\n".join(lines).strip())
            return

        parts = rest.split()
        if len(parts) != 2:
            bot.send_message(chat_id,
                "Format: /stokminimum SKU THRESHOLD atau /stokminimum SKU off\n"
                "Contoh: /stokminimum TG-BC-001 3")
            return

        sku, raw_val = parts[0], parts[1]
        if raw_val.lower() == "off":
            action = "REMOVE"
            new_threshold = None
        else:
            try:
                new_threshold = int(raw_val)
            except ValueError:
                bot.send_message(chat_id, "Batas stok minimum harus berupa angka bulat non-negatif atau 'off'.")
                return
            if new_threshold < 0:
                bot.send_message(chat_id, "Batas stok minimum harus bilangan bulat non-negatif (>= 0).")
                return
            action = "SET"

        draft = low_stock.create_threshold_draft(
            business_id=business_id,
            owner_id=owner_id,
            telegram_user_id=user_id,
            sku=sku,
            action=action,
            new_threshold=new_threshold,
        )
        if not draft.get("ok"):
            err = draft.get("error")
            if err == "unknown_sku":
                bot.send_message(chat_id, f"Produk dengan SKU '{sku}' tidak ditemukan di bisnis Anda.")
            else:
                bot.send_message(chat_id, "Gagal menyiapkan pengaturan stok minimum.")
            return

        preview_text = low_stock.render_threshold_preview(draft)
        bot.send_message(
            chat_id,
            preview_text,
            reply_markup={"inline_keyboard": [[
                {"text": "✅ Simpan", "callback_data": f"th_confirm:{draft['draft_token']}"},
                {"text": "❌ Batal", "callback_data": f"th_cancel:{draft['draft_token']}"},
            ]]},
        )
        return

    if text in ("/stokrendah", "/stokrendah@") or text.startswith("/stokrendah "):
        items = low_stock.list_low_stock_products(business_id=business_id)
        if not items:
            bot.send_message(chat_id, "✅ Tidak ada produk yang stoknya di bawah batas minimum.")
            return
        lines = ["⚠️ STOK MENIPIS", ""]
        for item in items:
            lines.append(f"• {item['product_name']}")
            lines.append(f"  SKU: {item['sku']}")
            lines.append(f"  Stok: {item['available']}")
            lines.append(f"  Minimum: {item['threshold']}")
            lines.append("")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/reorder"):
        rest = text[len("/reorder"):].strip()
        if not rest:
            recs = reorder_mod.calculate_reorder_recommendations(business_id=business_id)
            msg_text = reorder_mod.render_reorder_message(recs)
            bot.send_message(chat_id, msg_text)
            return

        sku = rest.strip()
        prod = low_stock.resolve_sku_product(business_id=business_id, sku=sku)
        if not prod:
            bot.send_message(chat_id, f"Produk dengan SKU '{sku}' tidak ditemukan di bisnis Anda.")
            return

        rec = reorder_mod.calculate_reorder_for_sku(business_id=business_id, master_sku_id=prod["master_sku_id"])
        msg_text = reorder_mod.render_reorder_message([rec], single_sku=True)
        bot.send_message(chat_id, msg_text)
        return

    # ------------------------------------------------------------ /supplier
    if text == "/supplier" or text == "/supplier@":
        supps = proc_mod.list_suppliers(business_id=business_id, active_only=True)
        if not supps:
            bot.send_message(chat_id, "Belum ada supplier yang terdaftar.\nGunakan /supplier tambah KODE|NAMA untuk menambah.")
            return
        lines = ["🏢 DAFTAR SUPPLIER", ""]
        for s in supps:
            lines.append(f"• [{s['code']}] {s['name']}")
            if s.get("phone"):
                lines.append(f"  Telp: {s['phone']}")
            if s.get("contact_name"):
                lines.append(f"  Kontak: {s['contact_name']}")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/supplier "):
        cmd_body = text[len("/supplier "):].strip()
        parts = cmd_body.split(maxsplit=1)
        sub = parts[0].lower()

        if sub == "tambah":
            if len(parts) < 2 or "|" not in parts[1]:
                bot.send_message(chat_id, "Format: /supplier tambah KODE|NAMA atau /supplier tambah KODE|NAMA|KONTAK|TELP")
                return
            fields = [f.strip() for f in parts[1].split("|")]
            scode = fields[0].upper()
            sname = fields[1] if len(fields) > 1 else ""
            scontact = fields[2] if len(fields) > 2 else ""
            sphone = fields[3] if len(fields) > 3 else ""
            if not scode or not sname:
                bot.send_message(chat_id, "Kode dan Nama supplier wajib diisi.")
                return

            draft = proc_mod.create_procurement_draft(
                draft_type="SUPPLIER_CREATE",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"code": scode, "name": sname, "contact_name": scontact, "phone": sphone},
            )
            preview_lines = [
                "🏢 TAMBAH SUPPLIER",
                "",
                f"Kode: {scode}",
                f"Nama: {sname}",
            ]
            if scontact:
                preview_lines.append(f"Kontak: {scontact}")
            if sphone:
                preview_lines.append(f"Telp: {sphone}")
            preview_lines.append("\nSimpan data supplier ini?")

            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Simpan", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        if sub == "ubah":
            if len(parts) < 2 or "|" not in parts[1]:
                bot.send_message(chat_id, "Format: /supplier ubah KODE|NAMA atau /supplier ubah KODE|NAMA|KONTAK|TELP")
                return
            fields = [f.strip() for f in parts[1].split("|")]
            scode = fields[0].upper()
            sname = fields[1] if len(fields) > 1 else ""
            scontact = fields[2] if len(fields) > 2 else None
            sphone = fields[3] if len(fields) > 3 else None

            existing = proc_mod.get_supplier(business_id=business_id, code=scode)
            if not existing:
                bot.send_message(chat_id, f"Supplier dengan kode '{scode}' tidak ditemukan.")
                return

            draft = proc_mod.create_procurement_draft(
                draft_type="SUPPLIER_EDIT",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"code": scode, "name": sname, "contact_name": scontact, "phone": sphone},
            )
            preview_lines = [
                "🏢 UBAH SUPPLIER",
                "",
                f"Kode: {scode}",
                f"Nama lama: {existing['name']}",
                f"Nama baru: {sname}",
            ]
            if scontact:
                preview_lines.append(f"Kontak: {scontact}")
            if sphone:
                preview_lines.append(f"Telp: {sphone}")
            preview_lines.append("\nSimpan perubahan data supplier ini?")

            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Simpan", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # Check if CODE off:
        words = cmd_body.split()
        if len(words) == 2 and words[1].lower() == "off":
            scode = words[0].upper()
            existing = proc_mod.get_supplier(business_id=business_id, code=scode)
            if not existing:
                bot.send_message(chat_id, f"Supplier dengan kode '{scode}' tidak ditemukan.")
                return
            draft = proc_mod.create_procurement_draft(
                draft_type="SUPPLIER_OFF",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"code": scode, "name": existing["name"]},
            )
            preview_lines = [
                "🏢 NONAKTIFKAN SUPPLIER",
                "",
                f"Kode: {scode}",
                f"Nama: {existing['name']}",
                "\nNonaktifkan supplier ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Nonaktifkan", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # Else query by code
        scode = cmd_body.strip().upper()
        supp = proc_mod.get_supplier(business_id=business_id, code=scode)
        if not supp:
            bot.send_message(chat_id, f"Supplier dengan kode '{scode}' tidak ditemukan.")
            return
        lines = [
            f"🏢 DETAIL SUPPLIER [{supp['code']}]",
            "",
            f"Nama: {supp['name']}",
            f"Kontak: {supp.get('contact_name') or '-'}",
            f"Telp: {supp.get('phone') or '-'}",
            f"Email: {supp.get('email') or '-'}",
            f"Alamat: {supp.get('address') or '-'}",
            f"Status: {'Aktif' if supp['active'] else 'Nonaktif'}",
        ]
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # ------------------------------------------------------------ /restockconfig
    if text == "/restockconfig" or text == "/restockconfig@":
        cfgs = proc_mod.list_supplier_skus(business_id=business_id)
        if not cfgs:
            bot.send_message(chat_id, "Belum ada konfigurasi restock yang diatur.\nGunakan /restockconfig SKU KODE_SUPPLIER|LEAD_TIME|MOQ|TARGET_STOK")
            return
        lines = ["⚙️ KONFIGURASI RESTOCK", ""]
        for c in cfgs:
            t_str = f" | Target stok: {c['target_stock']}" if c.get("target_stock") is not None else ""
            lines.append(f"• {c['product_name']} ({c['sku']})")
            lines.append(f"  Supplier: {c['supplier_name']} [{c['supplier_code']}]")
            lines.append(f"  Lead time: {c['lead_time_days']} hari | MOQ: {c['min_order_qty']}{t_str}")
            lines.append("")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/restockconfig "):
        cmd_body = text[len("/restockconfig "):].strip()
        parts = cmd_body.split(maxsplit=1)
        sku = parts[0].strip()

        prod = low_stock.resolve_sku_product(business_id=business_id, sku=sku)
        if not prod:
            bot.send_message(chat_id, f"Produk dengan SKU '{sku}' tidak ditemukan di bisnis Anda.")
            return

        if len(parts) == 1:
            # Query single SKU
            cfg = proc_mod.get_preferred_supplier_sku(business_id=business_id, master_sku_id=prod["master_sku_id"])
            if not cfg:
                bot.send_message(chat_id, f"Belum ada konfigurasi restock untuk SKU '{sku}'.\nGunakan /restockconfig {sku} KODE_SUPPLIER|LEAD_TIME|MOQ|TARGET_STOK")
                return
            t_str = f"{cfg['target_stock']}" if cfg.get("target_stock") is not None else "Belum diatur"
            lines = [
                "⚙️ KONFIGURASI RESTOCK",
                "",
                f"Produk: {prod['product_name']}",
                f"SKU: {sku}",
                f"Supplier: {cfg['supplier_name']} [{cfg['supplier_code']}]",
                f"Lead time: {cfg['lead_time_days']} hari",
                f"Minimum order: {cfg['min_order_qty']}",
                f"Target stok: {t_str}",
            ]
            bot.send_message(chat_id, "\n".join(lines).strip())
            return

        arg_val = parts[1].strip()
        if arg_val.lower() == "off":
            draft = proc_mod.create_procurement_draft(
                draft_type="RESTOCK_OFF",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"master_sku_id": prod["master_sku_id"], "sku": sku},
            )
            preview_lines = [
                "⚙️ NONAKTIFKAN RESTOCK CONFIG",
                "",
                f"Produk: {prod['product_name']}",
                f"SKU: {sku}",
                "\nNonaktifkan konfigurasi restock untuk SKU ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Nonaktifkan", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        if "|" not in arg_val:
            bot.send_message(chat_id, f"Format:\n/restockconfig {sku} KODE_SUPPLIER|LEAD_TIME|MOQ|TARGET_STOK\n/restockconfig {sku} KODE_SUPPLIER|LEAD_TIME|MOQ|TARGET_STOK|HARGA_BELI")
            return

        cfields = [f.strip() for f in arg_val.split("|")]
        scode = cfields[0].upper()
        supp = proc_mod.get_supplier(business_id=business_id, code=scode)
        if not supp:
            bot.send_message(chat_id, f"Supplier dengan kode '{scode}' tidak ditemukan. Daftarkan supplier terlebih dahulu dengan /supplier tambah {scode}|NamaSupplier")
            return

        try:
            lead_days = int(cfields[1])
            if lead_days < 1:
                bot.send_message(chat_id, "Lead time harus berupa angka bulat >= 1 hari.")
                return
        except (IndexError, ValueError):
            bot.send_message(chat_id, "Lead time harus berupa angka bulat >= 1 hari.")
            return

        try:
            moq = int(cfields[2]) if len(cfields) > 2 and cfields[2] else 1
            if moq < 1:
                bot.send_message(chat_id, "Minimum order (MOQ) harus berupa angka bulat >= 1.")
                return
        except ValueError:
            bot.send_message(chat_id, "Minimum order (MOQ) harus berupa angka bulat >= 1.")
            return

        target_stk = None
        if len(cfields) > 3 and cfields[3]:
            try:
                target_stk = int(cfields[3])
                if target_stk < moq:
                    bot.send_message(chat_id, f"Target stok ({target_stk}) tidak boleh lebih kecil dari MOQ ({moq}).")
                    return
            except ValueError:
                bot.send_message(chat_id, "Target stok harus berupa angka bulat non-negatif.")
                return

        purchase_cost = None
        if len(cfields) > 4 and cfields[4]:
            try:
                clean_c = cfields[4].replace(".", "").replace(",", "").replace("Rp", "").replace("rp", "").strip()
                purchase_cost = float(Decimal(clean_c))
                if purchase_cost < 0:
                    bot.send_message(chat_id, "Harga beli (purchase cost) tidak boleh negatif.")
                    return
            except Exception:
                bot.send_message(chat_id, f"Harga beli '{cfields[4]}' tidak valid.")
                return

        draft = proc_mod.create_procurement_draft(
            draft_type="RESTOCK_CONFIG",
            business_id=business_id,
            owner_id=owner_id,
            telegram_user_id=user_id,
            payload={
                "master_sku_id": prod["master_sku_id"],
                "sku": sku,
                "supplier_id": supp["id"],
                "lead_time_days": lead_days,
                "min_order_qty": moq,
                "target_stock": target_stk,
                "purchase_unit_cost": purchase_cost,
            },
        )
        t_str = f"{target_stk}" if target_stk is not None else "Belum diatur"
        c_str = f"Rp{int(purchase_cost):,}" if purchase_cost is not None else "Belum diatur"
        preview_lines = [
            "⚙️ KONFIGURASI RESTOCK",
            "",
            f"Produk: {prod['product_name']}",
            f"SKU: {sku}",
            f"Supplier: {supp['name']} [{supp['code']}]",
            "",
            f"Lead time: {lead_days} hari",
            f"Minimum order (MOQ): {moq}",
            f"Target stok: {t_str}",
            f"Harga beli (PO): {c_str}",
            "\nSimpan konfigurasi restock ini?",
        ]
        tok = draft["draft_token"]
        kb = {
            "inline_keyboard": [[
                {"text": "✅ Simpan", "callback_data": f"pc_confirm:{tok}"},
                {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
            ]]
        }
        bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
        return

    # ------------------------------------------------------------ /po
    if text == "/po" or text == "/po@":
        pos = proc_mod.list_purchase_orders(business_id=business_id, limit=10)
        if not pos:
            bot.send_message(chat_id, "Belum ada Purchase Order.\nGunakan /po buat SKU untuk membuat PO dari rekomendasi restock.")
            return
        lines = ["📋 DAFTAR PURCHASE ORDER", ""]
        for p in pos:
            arr_str = f" | Tiba: {p['expected_arrival_date']}" if p.get("expected_arrival_date") else ""
            lines.append(f"• {p['po_number']} [{p['status']}]")
            lines.append(f"  Supplier: {p['supplier_name']}")
            lines.append(f"  Total: Rp{int(p['subtotal']):,}{arr_str}")
            lines.append("")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/po "):
        cmd_body = text[len("/po "):].strip()
        parts = cmd_body.split(maxsplit=1)
        sub = parts[0].lower()

        if sub == "buat":
            if len(parts) < 2:
                bot.send_message(chat_id, "Format: /po buat SKU atau /po buat KODE_SUPPLIER SKU:QTY")
                return
            bparts = parts[1].strip().split()
            if len(bparts) == 1 and ":" not in bparts[0]:
                # /po buat SKU (from reorder recommendation)
                sku = bparts[0].strip()
                prod = low_stock.resolve_sku_product(business_id=business_id, sku=sku)
                if not prod:
                    bot.send_message(chat_id, f"Produk dengan SKU '{sku}' tidak ditemukan di bisnis Anda.")
                    return

                qty = rec.get("suggested_order_qty", 0)
                if not qty or qty <= 0:
                    avail_stk = rec.get("available_stock", 0)
                    tgt_stk = rec.get("target_stock", 0)
                    bot.send_message(
                        chat_id,
                        f"Stok SKU '{sku}' saat ini ({int(avail_stk)}) masih memenuhi target ({int(tgt_stk)}).\n"
                        "Tidak ada rekomendasi pemesanan saat ini.\n\n"
                        f"Gunakan /po buat {rec['supplier_code']} {sku}:QTY untuk membuat PO manual.",
                    )
                    return

                unit_cost = rec.get("purchase_unit_cost") or 0
                today = datetime.now(timezone.utc).date()
                expected_date = today + timedelta(days=rec["lead_time_days"])

                draft = proc_mod.create_procurement_draft(
                    draft_type="PO_CREATE",
                    business_id=business_id,
                    owner_id=owner_id,
                    telegram_user_id=user_id,
                    payload={
                        "supplier_id": rec["supplier_id"],
                        "warehouse_id": warehouse_id or prod["warehouse_id"],
                        "expected_arrival_date": str(expected_date),
                        "lines": [{
                            "master_sku_id": prod["master_sku_id"],
                            "sku": sku,
                            "name": prod["product_name"],
                            "ordered_qty": qty,
                            "unit_cost": float(unit_cost),
                        }],
                    },
                )
                preview_lines = [
                    "📋 DRAFT PURCHASE ORDER",
                    "",
                    f"Supplier: {rec['supplier_name']} [{rec['supplier_code']}]",
                    f"Gudang: {biz_name}",
                    f"Produk: {prod['product_name']}",
                    f"SKU: {sku}",
                    f"Qty: {qty}",
                    f"Harga beli: Rp{int(unit_cost):,}" if unit_cost else "Harga beli: Belum diatur",
                    f"Estimasi tiba: {expected_date}",
                    "\nBuat draft PO ini?",
                ]
                tok = draft["draft_token"]
                kb = {
                    "inline_keyboard": [[
                        {"text": "✅ Buat Draft", "callback_data": f"pc_confirm:{tok}"},
                        {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                    ]]
                }
                bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
                return

            # /po buat KODE_SUPPLIER SKU:QTY
            scode = bparts[0].upper()
            supp = proc_mod.get_supplier(business_id=business_id, code=scode)
            if not supp:
                bot.send_message(chat_id, f"Supplier dengan kode '{scode}' tidak ditemukan.")
                return

            po_lines_payload = []
            for item_spec in bparts[1:]:
                if ":" not in item_spec:
                    bot.send_message(chat_id, f"Format item tidak valid '{item_spec}'. Gunakan SKU:QTY")
                    return
                is_sku, is_qty_str = item_spec.split(":", 1)
                is_sku = is_sku.strip()
                try:
                    is_qty = int(is_qty_str)
                    if is_qty <= 0:
                        bot.send_message(chat_id, f"Quantity untuk SKU '{is_sku}' harus > 0.")
                        return
                except ValueError:
                    bot.send_message(chat_id, f"Quantity untuk SKU '{is_sku}' tidak valid.")
                    return

                p_item = low_stock.resolve_sku_product(business_id=business_id, sku=is_sku)
                if not p_item:
                    bot.send_message(chat_id, f"Produk dengan SKU '{is_sku}' tidak ditemukan.")
                    return
                po_lines_payload.append({
                    "master_sku_id": p_item["master_sku_id"],
                    "sku": is_sku,
                    "name": p_item["product_name"],
                    "ordered_qty": is_qty,
                    "unit_cost": 0,
                })

            draft = proc_mod.create_procurement_draft(
                draft_type="PO_CREATE",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={
                    "supplier_id": supp["id"],
                    "warehouse_id": warehouse_id,
                    "lines": po_lines_payload,
                },
            )
            preview_lines = [
                "📋 DRAFT PURCHASE ORDER",
                "",
                f"Supplier: {supp['name']} [{supp['code']}]",
                f"Gudang: {biz_name}",
            ]
            for pl in po_lines_payload:
                preview_lines.append(f"• {pl['name']} ({pl['sku']}): {pl['ordered_qty']} pcs")
            preview_lines.append("\nBuat draft PO ini?")
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Buat Draft", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        if sub == "batal":
            if len(parts) < 2:
                bot.send_message(chat_id, "Format: /po batal NOMOR_PO")
                return
            po_num = parts[1].strip().upper()
            po = proc_mod.get_purchase_order(business_id=business_id, po_number=po_num)
            if not po:
                bot.send_message(chat_id, f"PO '{po_num}' tidak ditemukan.")
                return
            if po["status"] not in ("DRAFT", "CONFIRMED"):
                bot.send_message(chat_id, f"PO '{po_num}' dengan status {po['status']} tidak dapat dibatalkan.")
                return

            draft = proc_mod.create_procurement_draft(
                draft_type="PO_CANCEL",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"po_number": po_num},
            )
            preview_lines = [
                f"📋 BATALKAN PURCHASE ORDER {po_num}",
                "",
                f"Supplier: {po['supplier_name']}",
                f"Status: {po['status']}",
                f"Total: Rp{int(po['subtotal']):,}",
                "\nBatalkan Purchase Order ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Batalkan PO", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # Query single PO by number
        po_num = cmd_body.strip().upper()
        po = proc_mod.get_purchase_order(business_id=business_id, po_number=po_num)
        if not po:
            bot.send_message(chat_id, f"Purchase order '{po_num}' tidak ditemukan.")
            return

        lines = [
            f"📋 DETAIL PO: {po['po_number']}",
            "",
            f"Status: {po['status']}",
            f"Supplier: {po['supplier_name']} [{po['supplier_code']}]",
            f"Gudang: {po['warehouse_name']}",
            f"Estimasi tiba: {po.get('expected_arrival_date') or '-'}",
            f"Total: Rp{int(po['subtotal']):,}",
            "",
            "Item Pesanan:",
        ]
        for l in po.get("lines", []):
            lines.append(f"• {l['product_name']} ({l['sku']}): {l['received_qty']}/{l['ordered_qty']} pcs")

        if po["status"] == "DRAFT":
            draft_conf = proc_mod.create_procurement_draft(
                draft_type="PO_CONFIRM",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"po_number": po["po_number"]},
            )
            tok_conf = draft_conf["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Konfirmasi PO", "callback_data": f"pc_confirm:{tok_conf}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok_conf}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(lines).strip(), reply_markup=kb)
        else:
            bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # ------------------------------------------------------------ /terimapo
    if text.startswith("/terimapo"):
        rest = text[len("/terimapo"):].strip()
        if not rest:
            bot.send_message(chat_id, "Format: /terimapo NOMOR_PO atau /terimapo NOMOR_PO SKU:QTY")
            return

        rparts = rest.split()
        po_num = rparts[0].strip().upper()
        po = proc_mod.get_purchase_order(business_id=business_id, po_number=po_num)
        if not po:
            bot.send_message(chat_id, f"Purchase order '{po_num}' tidak ditemukan.")
            return

        if po["status"] == "DRAFT":
            bot.send_message(chat_id, f"PO '{po_num}' masih berstatus DRAFT. Konfirmasi PO terlebih dahulu dengan /po {po_num}")
            return
        if po["status"] == "RECEIVED":
            bot.send_message(chat_id, f"PO '{po_num}' sudah selesai diterima seluruhnya.")
            return
        if po["status"] == "CANCELLED":
            bot.send_message(chat_id, f"PO '{po_num}' sudah dibatalkan.")
            return

        # Determine lines to receive
        po_lines = po.get("lines", [])
        receive_lines_payload = []

        if len(rparts) > 1:
            custom_spec = {}
            for cs in rparts[1:]:
                if ":" in cs:
                    csku, cqty_str = cs.split(":", 1)
                    try:
                        custom_spec[csku.strip()] = int(cqty_str)
                    except ValueError:
                        pass

            for pl in po_lines:
                sku_key = pl["sku"]
                if sku_key in custom_spec:
                    rqty = custom_spec[sku_key]
                    rem = pl["ordered_qty"] - pl["received_qty"]
                    if rqty > rem:
                        bot.send_message(chat_id, f"Quantity penerimaan ({rqty}) melebihi sisa pesanan ({rem}) untuk SKU {sku_key}.")
                        return
                    if rqty > 0:
                        receive_lines_payload.append({
                            "master_sku_id": pl["master_sku_id"],
                            "sku": pl["sku"],
                            "name": pl["product_name"],
                            "quantity": rqty,
                            "unit_cost": float(pl["unit_cost"]),
                            "ordered_qty": pl["ordered_qty"],
                            "received_qty_before": pl["received_qty"],
                        })
        else:
            for pl in po_lines:
                rem = pl["ordered_qty"] - pl["received_qty"]
                if rem > 0:
                    receive_lines_payload.append({
                        "master_sku_id": pl["master_sku_id"],
                        "sku": pl["sku"],
                        "name": pl["product_name"],
                        "quantity": rem,
                        "unit_cost": float(pl["unit_cost"]),
                        "ordered_qty": pl["ordered_qty"],
                        "received_qty_before": pl["received_qty"],
                    })

        if not receive_lines_payload:
            bot.send_message(chat_id, f"Tidak ada item yang tersisa untuk diterima pada PO '{po_num}'.")
            return

        draft = proc_mod.create_procurement_draft(
            draft_type="PO_RECEIVE",
            business_id=business_id,
            owner_id=owner_id,
            telegram_user_id=user_id,
            payload={
                "po_number": po_num,
                "lines": receive_lines_payload,
            },
        )

        preview_lines = [
            "📦 PENERIMAAN PO",
            "",
            f"PO: {po['po_number']}",
            f"Supplier: {po['supplier_name']}",
            f"Gudang: {po['warehouse_name']}",
            "",
        ]
        for rlp in receive_lines_payload:
            preview_lines.append(f"• {rlp['name']}")
            preview_lines.append(f"  Dipesan: {rlp['ordered_qty']}")
            preview_lines.append(f"  Sudah diterima: {rlp['received_qty_before']}")
            preview_lines.append(f"  Akan diterima: {rlp['quantity']}")
            preview_lines.append(f"  Sisa: {rlp['ordered_qty'] - rlp['received_qty_before'] - rlp['quantity']}")
            preview_lines.append("")

        preview_lines.append("Terima barang ini ke stok?")
        tok = draft["draft_token"]
        kb = {
            "inline_keyboard": [[
                {"text": "✅ Terima Barang", "callback_data": f"pc_confirm:{tok}"},
                {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
            ]]
        }
        bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
        return

    # ------------------------------------------------------------
    # /tagihan: VENDOR BILL
    # ------------------------------------------------------------
    if text in ("/tagihan", "/tagihan@"):
        bills = proc_mod.list_vendor_bills(business_id=business_id, limit=10)
        if not bills:
            bot.send_message(
                chat_id,
                "Belum ada tagihan supplier tercatat.\n\n"
                "Gunakan /tagihan buat NOMOR_PO untuk membuat draft tagihan dari penerimaan barang PO.",
            )
            return

        out_lines = ["🧾 DAFTAR TAGIHAN SUPPLIER", ""]
        for b in bills:
            out_lines.append(f"• {b['bill_number']}")
            out_lines.append(f"  Supplier: {b['supplier_name']}")
            out_lines.append(f"  Total: Rp{int(b['total']):,}")
            out_lines.append(f"  Dibayar: Rp{int(b['paid_amount']):,}")
            out_lines.append(f"  Sisa: Rp{int(b['outstanding_amount']):,}")
            out_lines.append(f"  Status: {b['status']} (Match: {b['match_status']})")
            out_lines.append("")
        out_lines.append("Ketik /tagihan NOMOR untuk detail tagihan.")
        bot.send_message(chat_id, "\n".join(out_lines).strip())
        return

    if text.startswith("/tagihan "):
        arg = text[9:].strip()
        if not arg:
            bot.send_message(chat_id, "Gunakan:\n/tagihan - daftar tagihan\n/tagihan NOMOR - detail tagihan\n/tagihan buat NOMOR_PO - buat draft tagihan\n/tagihan posting NOMOR - posting tagihan ke Utang\n/tagihan batal NOMOR - batalkan draft tagihan")
            return

        # /tagihan buat PO_NUMBER [VENDOR_REF|UNIT_COST]
        if arg.startswith("buat ") or arg == "buat":
            raw_arg = arg[5:].strip() if len(arg) > 4 else ""
            if not raw_arg:
                bot.send_message(
                    chat_id,
                    "Format: /tagihan buat NOMOR_PO [NO_INVOICE|HARGA_SATUAN]\n\n"
                    "Contoh:\n"
                    "/tagihan buat BC-PO-2026-000001\n"
                    "/tagihan buat BC-PO-2026-000001 INV-SUP-001|5000",
                )
                return

            b_parts = raw_arg.split(None, 1)
            po_arg = b_parts[0].strip().upper()
            vendor_ref = None
            custom_unit_cost = None

            if len(b_parts) > 1:
                ref_spec = b_parts[1].strip()
                if "|" in ref_spec:
                    v_part, c_part = ref_spec.split("|", 1)
                    vendor_ref = v_part.strip() or None
                    clean_c = c_part.replace(".", "").replace(",", "").replace("Rp", "").replace("rp", "").strip()
                    if clean_c:
                        try:
                            custom_unit_cost = Decimal(clean_c)
                            if custom_unit_cost < Decimal("0"):
                                bot.send_message(chat_id, "Harga invoice tidak boleh negatif.")
                                return
                        except Exception:
                            bot.send_message(chat_id, f"Harga invoice '{c_part}' tidak valid.")
                            return
                else:
                    vendor_ref = ref_spec

            po = proc_mod.get_purchase_order(business_id=business_id, po_number=po_arg)
            if not po:
                bot.send_message(chat_id, f"Purchase order '{po_arg}' tidak ditemukan.")
                return

            cur_lines = po.get("lines", [])
            total_rcv = sum(int(l["received_qty"]) for l in cur_lines)
            if total_rcv == 0:
                bot.send_message(
                    chat_id,
                    f"❌ Barang untuk PO {po['po_number']} belum pernah diterima di gudang.\n\n"
                    f"Status 3-Way Match: MISSING_RECEIPT\n"
                    f"Gunakan /terimapo {po['po_number']} terlebih dahulu.",
                )
                return

            bill_lines_payload = []
            subtotal = Decimal("0")
            for pol in cur_lines:
                rcv = int(pol["received_qty"])
                if rcv > 0:
                    po_uc = Decimal(str(pol["unit_cost"]))
                    actual_uc = custom_unit_cost if custom_unit_cost is not None else po_uc
                    ltot = Decimal(str(rcv)) * actual_uc
                    subtotal += ltot
                    bill_lines_payload.append({
                        "purchase_order_line_id": pol["id"],
                        "master_sku_id": pol["master_sku_id"],
                        "sku": pol["sku"],
                        "description": pol.get("description") or pol.get("product_name") or pol["sku"],
                        "quantity": rcv,
                        "unit_cost": float(actual_uc),
                        "po_unit_cost": float(po_uc),
                        "tax_amount": 0.0,
                        "line_total": float(ltot),
                    })

            if not bill_lines_payload:
                bot.send_message(chat_id, f"Tidak ada item yang dapat ditagihkan pada PO {po['po_number']}.")
                return

            match_res = proc_mod.match_purchase_order_goods_receipt_bill(
                business_id=business_id,
                po_id=po["id"],
                bill_lines=bill_lines_payload,
            )
            m_stat = match_res.get("match_status", "UNKNOWN")

            if m_stat == "MISSING_COST":
                missing_skus = match_res.get("missing_skus", [])
                bot.send_message(
                    chat_id,
                    f"❌ Harga beli PO belum diatur untuk SKU: {', '.join(missing_skus)}.\n\n"
                    f"Status 3-Way Match: MISSING_COST\n"
                    f"Atur harga beli terlebih dahulu dengan /restockconfig agar PO dan tagihan bernilai valid.",
                )
                return

            draft = proc_mod.create_procurement_draft(
                draft_type="VENDOR_BILL_CREATE",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={
                    "supplier_id": po["supplier_id"],
                    "purchase_order_id": po["id"],
                    "po_number": po["po_number"],
                    "vendor_reference": vendor_ref,
                    "lines": bill_lines_payload,
                },
            )

            preview_lines = [
                "🧾 DRAFT TAGIHAN SUPPLIER",
                "",
                f"Supplier: {po['supplier_name']}",
                f"PO: {po['po_number']}",
                f"Invoice Supplier: {vendor_ref or '-'}",
                "",
                "Rincian Barang & Harga:",
            ]
            for blp in bill_lines_payload:
                preview_lines.append(f"• {blp['sku']}")
                preview_lines.append(f"  Diterima: {blp['quantity']} | Ditagih: {blp['quantity']}")
                preview_lines.append(f"  Harga PO: Rp{int(blp['po_unit_cost']):,} | Harga Invoice: Rp{int(blp['unit_cost']):,}")
                preview_lines.append(f"  Subtotal: Rp{int(blp['line_total']):,}")
                preview_lines.append("")

            preview_lines.append(f"Total Tagihan: Rp{int(subtotal):,}")
            preview_lines.append(f"Hasil 3-Way Match: {m_stat}")
            if m_stat != "MATCHED":
                preview_lines.append(f"⚠️ Perhatian: {match_res.get('message', '')}")
            preview_lines.append("")
            preview_lines.append("Buat draft tagihan ini?")

            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Buat Draft", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # /tagihan posting BILL_NUMBER
        if arg.startswith("posting ") or arg == "posting":
            bill_arg = arg[8:].strip() if len(arg) > 7 else ""
            if not bill_arg:
                bot.send_message(chat_id, "Format: /tagihan posting NOMOR_TAGIHAN\nContoh: /tagihan posting BC-VB-2026-000001")
                return

            bill = proc_mod.get_vendor_bill(business_id=business_id, bill_number=bill_arg)
            if not bill:
                bot.send_message(chat_id, f"Tagihan '{bill_arg}' tidak ditemukan.")
                return

            if bill["status"] != "DRAFT":
                bot.send_message(chat_id, f"Tagihan {bill['bill_number']} status {bill['status']} tidak dapat diposting.")
                return

            if bill["match_status"] != "MATCHED":
                bot.send_message(chat_id, f"❌ Tagihan {bill['bill_number']} memiliki status 3-Way Match '{bill['match_status']}' dan tidak dapat diposting otomatis.")
                return

            draft = proc_mod.create_procurement_draft(
                draft_type="VENDOR_BILL_POST",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"bill_number": bill["bill_number"]},
            )

            preview_lines = [
                "🧾 POSTING TAGIHAN SUPPLIER",
                "",
                f"Supplier: {bill['supplier_name']}",
                f"Tagihan: {bill['bill_number']}",
                f"Total: Rp{int(bill['total']):,}",
                "",
                "Dampak Akuntansi Keuangan:",
                f"• Dr Persediaan Barang (1301): Rp{int(bill['total']):,}",
                f"• Cr Utang Usaha (2101): Rp{int(bill['total']):,}",
                "",
                "Posting tagihan ini ke Buku Besar & Utang Usaha?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Posting", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # /tagihan batal BILL_NUMBER
        if arg.startswith("batal ") or arg == "batal":
            bill_arg = arg[6:].strip() if len(arg) > 5 else ""
            if not bill_arg:
                bot.send_message(chat_id, "Format: /tagihan batal NOMOR_TAGIHAN\nContoh: /tagihan batal BC-VB-2026-000001")
                return

            bill = proc_mod.get_vendor_bill(business_id=business_id, bill_number=bill_arg)
            if not bill:
                bot.send_message(chat_id, f"Tagihan '{bill_arg}' tidak ditemukan.")
                return

            if bill["status"] != "DRAFT":
                bot.send_message(chat_id, f"Tagihan {bill['bill_number']} status {bill['status']} tidak dapat dibatalkan.")
                return

            draft = proc_mod.create_procurement_draft(
                draft_type="VENDOR_BILL_CANCEL",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"bill_number": bill["bill_number"]},
            )

            preview_lines = [
                "❌ BATALKAN DRAFT TAGIHAN",
                "",
                f"Supplier: {bill['supplier_name']}",
                f"Tagihan: {bill['bill_number']}",
                f"Total: Rp{int(bill['total']):,}",
                "",
                "Batalkan draft tagihan ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Batalkan", "callback_data": f"pc_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # Single bill detail view /tagihan BILL_NUMBER
        bill = proc_mod.get_vendor_bill(business_id=business_id, bill_number=arg)
        if not bill:
            bot.send_message(chat_id, f"Tagihan '{arg}' tidak ditemukan.\nGunakan /tagihan untuk melihat daftar tagihan.")
            return

        lines = [
            f"🧾 DETAIL TAGIHAN: {bill['bill_number']}",
            "",
            f"Supplier: {bill['supplier_name']}",
            f"PO: {bill.get('po_number') or '-'}",
            f"Tanggal: {bill['bill_date']}",
            f"Jatuh Tempo: {bill['due_date']}",
            f"Status: {bill['status']}",
            f"3-Way Match: {bill['match_status']}",
            "",
            "Item:",
        ]
        for l in bill.get("lines", []):
            lines.append(f"• {l.get('sku') or l['description']} x {int(l['quantity'])} @ Rp{int(l['unit_cost']):,} = Rp{int(l['line_total']):,}")
        lines.append("")
        lines.append(f"Total: Rp{int(bill['total']):,}")
        lines.append(f"Sudah Dibayar: Rp{int(bill['paid_amount']):,}")
        lines.append(f"Sisa (Outstanding): Rp{int(bill['outstanding_amount']):,}")

        if bill["status"] == "DRAFT":
            lines.append("\nAksi: /tagihan posting " + bill["bill_number"] + " | /tagihan batal " + bill["bill_number"])
        elif bill["status"] in ("POSTED", "PARTIALLY_PAID"):
            lines.append("\nAksi: /bayar " + bill["bill_number"] + " " + str(int(bill["outstanding_amount"])))

        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # ------------------------------------------------------------
    # /bayar: VENDOR PAYMENT
    # ------------------------------------------------------------
    if text in ("/bayar", "/bayar@"):
        bot.send_message(
            chat_id,
            "Format pembayaran tagihan:\n"
            "/bayar NOMOR_TAGIHAN JUMLAH\n"
            "/bayar NOMOR_TAGIHAN JUMLAH BANK\n\n"
            "Contoh:\n"
            "/bayar BC-VB-2026-000001 500000\n"
            "/bayar BC-VB-2026-000001 500000 BANK",
        )
        return

    if text.startswith("/bayar "):
        raw_args = text[7:].strip().split()
        if len(raw_args) < 2:
            bot.send_message(chat_id, "Format: /bayar NOMOR_TAGIHAN JUMLAH [KAS|BANK]\nContoh: /bayar BC-VB-2026-000001 500000")
            return

        bill_num = raw_args[0].strip().upper()
        amount_clean = raw_args[1].replace(".", "").replace(",", "").replace("Rp", "").replace("rp", "").strip()
        try:
            pay_amount = Decimal(amount_clean)
        except Exception:
            bot.send_message(chat_id, f"Jumlah pembayaran '{raw_args[1]}' tidak valid.")
            return

        if pay_amount <= Decimal("0"):
            bot.send_message(chat_id, "❌ Jumlah pembayaran harus lebih besar dari 0.")
            return

        acc_choice = raw_args[2].strip().upper() if len(raw_args) >= 3 else "KAS"

        bill = proc_mod.get_vendor_bill(business_id=business_id, bill_number=bill_num)
        if not bill:
            bot.send_message(chat_id, f"Tagihan '{bill_num}' tidak ditemukan.")
            return

        if bill["status"] == "DRAFT":
            bot.send_message(chat_id, f"❌ Tagihan {bill_num} masih DRAFT. Posting tagihan terlebih dahulu dengan /tagihan posting {bill_num}.")
            return

        if bill["status"] == "CANCELLED":
            bot.send_message(chat_id, f"❌ Tagihan {bill_num} sudah dibatalkan.")
            return

        if bill["status"] == "PAID":
            bot.send_message(chat_id, f"❌ Tagihan {bill_num} sudah lunas (PAID).")
            return

        outstanding = Decimal(str(bill["outstanding_amount"]))
        if pay_amount > outstanding:
            bot.send_message(chat_id, f"❌ Jumlah pembayaran (Rp{int(pay_amount):,}) melebihi sisa tagihan (Rp{int(outstanding):,}).")
            return

        _, acc_label = proc_mod.resolve_cash_account(acc_choice)
        remaining_after = outstanding - pay_amount

        draft = proc_mod.create_procurement_draft(
            draft_type="VENDOR_PAYMENT",
            business_id=business_id,
            owner_id=owner_id,
            telegram_user_id=user_id,
            payload={
                "bill_number": bill["bill_number"],
                "amount": float(pay_amount),
                "payment_account_id": acc_choice,
            },
        )

        preview_lines = [
            "💳 PEMBAYARAN TAGIHAN SUPPLIER",
            "",
            f"Supplier: {bill['supplier_name']}",
            f"Tagihan: {bill['bill_number']}",
            f"Total: Rp{int(bill['total']):,}",
            f"Sudah dibayar: Rp{int(bill['paid_amount']):,}",
            f"Outstanding: Rp{int(outstanding):,}",
            "",
            f"Pembayaran sekarang: Rp{int(pay_amount):,}",
            f"Sisa setelah bayar: Rp{int(remaining_after):,}",
            f"Akun pembayaran: {acc_label}",
            "",
            "Dampak Akuntansi Keuangan:",
            f"• Dr Utang Usaha (2101): Rp{int(pay_amount):,}",
            f"• Cr {acc_label}: Rp{int(pay_amount):,}",
            "",
            "Konfirmasi pencatatan pembayaran ini?",
        ]

        tok = draft["draft_token"]
        kb = {
            "inline_keyboard": [[
                {"text": "✅ Bayar", "callback_data": f"pc_confirm:{tok}"},
                {"text": "❌ Batal", "callback_data": f"pc_cancel:{tok}"},
            ]]
        }
        bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
        return


    # ------------------------------------------------------------
    # /pelanggan: CUSTOMER MASTER
    # ------------------------------------------------------------
    if text in ("/pelanggan", "/pelanggan@"):
        customers = sales_mod.list_customers(business_id=business_id, active_only=True)
        if not customers:
            bot.send_message(chat_id, "Belum ada data pelanggan.\n\nUntuk menambah pelanggan:\n/pelanggan tambah KODE|NAMA\n/pelanggan tambah KODE|NAMA|TELEPON|TERMS_HARI|CREDIT_LIMIT")
            return
        lines = ["👥 DAFTAR PELANGGAN", ""]
        for c in customers:
            lim_str = f"Rp{int(c['credit_limit']):,}" if c.get("credit_limit") else "Tidak ada limit"
            lines.append(f"• {c['name']} ({c['code']})")
            if c.get("phone"):
                lines.append(f"  Telp: {c['phone']}")
            lines.append(f"  Terms: {c.get('payment_terms_days', 30)} hari | Limit: {lim_str}")
            lines.append("")
        lines.append("Aksi: /pelanggan KODE | /pelanggan tambah KODE|NAMA")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/pelanggan "):
        arg = text[len("/pelanggan "):].strip()

        # /pelanggan tambah KODE|NAMA[|PHONE|TERMS|LIMIT]
        if arg.startswith("tambah ") or arg == "tambah":
            raw = arg[7:].strip() if len(arg) > 6 else ""
            if not raw or "|" not in raw:
                bot.send_message(chat_id, "Format: /pelanggan tambah KODE|NAMA\natau\n/pelanggan tambah KODE|NAMA|TELEPON|TERMS_HARI|CREDIT_LIMIT\n\nContoh:\n/pelanggan tambah CUST01|Toko Berkah\n/pelanggan tambah CUST01|Toko Berkah|08123456789|30|5000000")
                return

            parts = [p.strip() for p in raw.split("|")]
            code = parts[0].upper()
            name = parts[1] if len(parts) > 1 else ""
            phone = parts[2] if len(parts) > 2 else ""
            terms = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 30
            limit_val = Decimal(parts[4]) if len(parts) > 4 and parts[4] else None

            existing = sales_mod.get_customer(business_id=business_id, code_or_id=code)
            if existing and existing.get("active"):
                bot.send_message(chat_id, f"Pelanggan dengan kode '{code}' sudah ada: {existing['name']}.")
                return

            draft = sales_mod.create_sales_draft(
                draft_type="CUSTOMER_CREATE",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={
                    "code": code,
                    "name": name,
                    "phone": phone,
                    "payment_terms_days": terms,
                    "credit_limit": float(limit_val) if limit_val is not None else None,
                },
            )

            preview_lines = [
                "👤 TAMBAH PELANGGAN BARU",
                "",
                f"Kode: {code}",
                f"Nama: {name}",
                f"Telepon: {phone or '-'}",
                f"Payment Terms: {terms} hari",
                f"Credit Limit: Rp{int(limit_val):,}" if limit_val is not None else "Credit Limit: -",
                "",
                "Simpan pelanggan ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Simpan", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # /pelanggan KODE off
        if arg.endswith(" off"):
            code = arg[:-4].strip().upper()
            cust = sales_mod.get_customer(business_id=business_id, code_or_id=code)
            if not cust:
                bot.send_message(chat_id, f"Pelanggan '{code}' tidak ditemukan.")
                return

            draft = sales_mod.create_sales_draft(
                draft_type="CUSTOMER_OFF",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"code": code},
            )

            preview_lines = [
                "⚠️ NONAKTIFKAN PELANGGAN",
                "",
                f"Kode: {cust['code']}",
                f"Nama: {cust['name']}",
                "",
                "Nonaktifkan pelanggan ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Nonaktifkan", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # Single customer detail: /pelanggan KODE
        cust = sales_mod.get_customer(business_id=business_id, code_or_id=arg)
        if not cust:
            bot.send_message(chat_id, f"Pelanggan '{arg}' tidak ditemukan.\nGunakan /pelanggan untuk melihat daftar.")
            return

        exp = sales_mod.get_customer_ar_exposure(business_id=business_id, customer_id=cust["id"])
        lim_str = f"Rp{int(exp['credit_limit']):,}" if exp['credit_limit'] > 0 else "Tidak dibatasi"
        status_str = "AKTIF" if cust["active"] else "NONAKTIF"

        lines = [
            f"👤 DETAIL PELANGGAN: {cust['name']}",
            "",
            f"Kode: {cust['code']}",
            f"Status: {status_str}",
            f"Telepon: {cust.get('phone') or '-'}",
            f"Email: {cust.get('email') or '-'}",
            f"Alamat Kirim: {cust.get('delivery_address') or '-'}",
            f"Payment Terms: {cust.get('payment_terms_days', 30)} hari",
            f"Credit Limit: {lim_str}",
            "",
            "Status Piutang & Eksposur:",
            f"• Piutang Berjalan (AR): Rp{int(exp['ar_outstanding']):,}",
            f"• Pesanan Terbuka: Rp{int(exp['open_order_exposure']):,}",
            f"• Total Eksposur: Rp{int(exp['total_exposure']):,}",
        ]
        if exp["is_over_limit"]:
            lines.append("⚠️ PERINGATAN: Total eksposur melebihi batas kredit!")

        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # ------------------------------------------------------------
    # /penawaran: SALES QUOTATION
    # ------------------------------------------------------------
    if text in ("/penawaran", "/penawaran@"):
        from ..persistence.db import semua
        quotes = semua(
            """SELECT sq.*, c.name AS customer_name, c.code AS customer_code
               FROM local_business.sales_quotation sq
               JOIN local_business.customer c ON c.id=sq.customer_id
               WHERE sq.business_id=%s ORDER BY sq.id DESC LIMIT 10""",
            (business_id,),
        )
        if not quotes:
            bot.send_message(chat_id, "Belum ada penawaran harga.\n\nUntuk membuat penawaran:\n/penawaran buat KODE_PELANGGAN SKU:QTY\nContoh:\n/penawaran buat CUST01 TG-BC-001:5")
            return
        lines = ["📝 DAFTAR PENAWARAN HARGA (QUOTATION)", ""]
        for q in quotes:
            lines.append(f"• {q['quotation_number']} | {q['customer_name']} ({q['customer_code']})")
            lines.append(f"  Total: Rp{int(q['total']):,} | Status: {q['status']}")
            lines.append(f"  Berlaku s/d: {q['expiry_date']}")
            lines.append("")
        lines.append("Aksi: /penawaran NOMOR | /penawaran buat KODE SKU:QTY")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/penawaran "):
        arg = text[len("/penawaran "):].strip()

        # /penawaran buat KODE_PELANGGAN SKU:QTY [SKU:QTY...]
        if arg.startswith("buat ") or arg == "buat":
            raw = arg[5:].strip() if len(arg) > 4 else ""
            parts = raw.split()
            if len(parts) < 2:
                bot.send_message(chat_id, "Format: /penawaran buat KODE_PELANGGAN SKU:QTY [SKU:QTY...]\nContoh: /penawaran buat CUST01 TG-BC-001:5")
                return

            cust_code = parts[0].upper()
            cust = sales_mod.get_customer(business_id=business_id, code_or_id=cust_code)
            if not cust:
                bot.send_message(chat_id, f"Pelanggan '{cust_code}' tidak ditemukan.")
                return

            items_to_quote = []
            for it in parts[1:]:
                if ":" not in it:
                    bot.send_message(chat_id, f"Format item salah: '{it}'. Gunakan SKU:QTY (contoh: TG-BC-001:5)")
                    return
                sku_p, qty_p = it.split(":", 1)
                try:
                    qty_val = int(qty_p)
                except ValueError:
                    bot.send_message(chat_id, f"Jumlah '{qty_p}' harus berupa bilangan bulat.")
                    return
                items_to_quote.append({"sku": sku_p.strip(), "quantity": qty_val})

            try:
                from ..persistence.db import ambil
                preview_lines = [
                    "📝 DRAFT PENAWARAN HARGA (QUOTATION)",
                    "",
                    f"Pelanggan: {cust['name']} ({cust['code']})",
                    f"Terms: {cust.get('payment_terms_days', 30)} hari",
                    "",
                    "Item Penawaran:",
                ]
                subtotal = Decimal("0")
                resolved_payload_lines = []
                for it in items_to_quote:
                    msku = ambil("SELECT m.id, m.sku, p.name FROM multichannel.master_sku m JOIN multichannel.product p ON p.id=m.product_id WHERE m.sku=%s", (it["sku"],))
                    if not msku:
                        bot.send_message(chat_id, f"SKU '{it['sku']}' tidak ditemukan.")
                        return
                    sp = sales_mod.get_canonical_selling_price(business_id=business_id, master_sku_id=msku["id"])
                    if sp is None:
                        bot.send_message(chat_id, f"Harga jual untuk SKU '{it['sku']}' belum dikonfigurasi.")
                        return
                    line_tot = sp * it["quantity"]
                    subtotal += line_tot
                    preview_lines.append(f"• {msku['name']} ({msku['sku']}) x {it['quantity']} @ Rp{int(sp):,} = Rp{int(line_tot):,}")
                    resolved_payload_lines.append({
                        "master_sku_id": msku["id"],
                        "sku": msku["sku"],
                        "description": msku["name"],
                        "quantity": it["quantity"],
                        "unit_price": float(sp),
                    })

                preview_lines.append("")
                preview_lines.append(f"Total Penawaran: Rp{int(subtotal):,}")
                preview_lines.append("Masa Berlaku: 14 hari")
                preview_lines.append("")
                preview_lines.append("Konfirmasi pembuatan draft penawaran harga ini?")

                draft = sales_mod.create_sales_draft(
                    draft_type="QUOTATION_CREATE",
                    business_id=business_id,
                    owner_id=owner_id,
                    telegram_user_id=user_id,
                    payload={
                        "customer_id": cust["id"],
                        "lines": resolved_payload_lines,
                        "validity_days": 14,
                    },
                )
                tok = draft["draft_token"]
                kb = {
                    "inline_keyboard": [[
                        {"text": "✅ Buat Penawaran", "callback_data": f"sl_confirm:{tok}"},
                        {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                    ]]
                }
                bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
                return
            except Exception as e:
                bot.send_message(chat_id, f"Gagal membuat draft penawaran: {e}")
                return

        # /penawaran terima NOMOR
        if arg.startswith("terima ") or arg == "terima":
            q_num = arg[7:].strip() if len(arg) > 6 else ""
            if not q_num:
                bot.send_message(chat_id, "Format: /penawaran terima NOMOR_PENAWARAN")
                return

            draft = sales_mod.create_sales_draft(
                draft_type="QUOTATION_ACCEPT",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"quotation_number": q_num},
            )
            preview_lines = [
                "✅ PERSETUJUAN PENAWARAN HARGA",
                "",
                f"Nomor: {q_num}",
                "",
                "Setujui penawaran harga ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Setujui", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # /penawaran konversi NOMOR [GUDANG_ID]
        if arg.startswith("konversi ") or arg == "konversi":
            parts = arg[9:].strip().split()
            if not parts:
                bot.send_message(chat_id, "Format: /penawaran konversi NOMOR_PENAWARAN")
                return
            q_num = parts[0]
            wh_target = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else warehouse_id

            draft = sales_mod.create_sales_draft(
                draft_type="QUOTATION_CONVERT",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"quotation_number": q_num, "warehouse_id": wh_target},
            )
            preview_lines = [
                "🔄 KONVERSI PENAWARAN KE SALES ORDER",
                "",
                f"Nomor Penawaran: {q_num}",
                f"Gudang: ID {wh_target}",
                "",
                "Konversi penawaran ini menjadi Sales Order resmi?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Konversi ke SO", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # /penawaran batal NOMOR
        if arg.startswith("batal ") or arg == "batal":
            q_num = arg[6:].strip() if len(arg) > 5 else ""
            if not q_num:
                bot.send_message(chat_id, "Format: /penawaran batal NOMOR_PENAWARAN")
                return

            draft = sales_mod.create_sales_draft(
                draft_type="QUOTATION_CANCEL",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"quotation_number": q_num},
            )
            preview_lines = [
                "❌ BATALKAN PENAWARAN HARGA",
                "",
                f"Nomor: {q_num}",
                "",
                "Batalkan penawaran harga ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Batalkan", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # Detail view /penawaran NOMOR
        from ..persistence.db import ambil, semua
        quot = ambil(
            """SELECT sq.*, c.name AS customer_name, c.code AS customer_code
               FROM local_business.sales_quotation sq
               JOIN local_business.customer c ON c.id=sq.customer_id
               WHERE sq.business_id=%s AND sq.quotation_number=%s""",
            (business_id, arg),
        )
        if not quot:
            bot.send_message(chat_id, f"Penawaran '{arg}' tidak ditemukan.")
            return

        qlines = semua("""SELECT * FROM local_business.sales_quotation_line WHERE quotation_id=%s ORDER BY line_no""", (quot["id"],))
        lines = [
            f"📝 DETAIL PENAWARAN: {quot['quotation_number']}",
            "",
            f"Pelanggan: {quot['customer_name']} ({quot['customer_code']})",
            f"Tanggal: {quot['quotation_date']}",
            f"Berlaku s/d: {quot['expiry_date']}",
            f"Status: {quot['status']}",
            "",
            "Item:",
        ]
        for l in qlines:
            lines.append(f"• {l['description']} ({l['sku']}) x {l['quantity']} @ Rp{int(l['unit_price']):,} = Rp{int(l['line_total']):,}")
        lines.append("")
        lines.append(f"Total: Rp{int(quot['total']):,}")

        if quot["status"] in ("DRAFT", "SENT"):
            lines.append("\nAksi: /penawaran terima " + quot["quotation_number"] + " | /penawaran batal " + quot["quotation_number"])
        elif quot["status"] == "ACCEPTED":
            lines.append("\nAksi: /penawaran konversi " + quot["quotation_number"])

        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # ------------------------------------------------------------
    # /salesorder: SALES ORDER
    # ------------------------------------------------------------
    if text in ("/salesorder", "/salesorder@"):
        from ..persistence.db import semua
        orders = semua(
            """SELECT so.*, c.name AS customer_name, c.code AS customer_code
               FROM local_business.sales_order so
               JOIN local_business.customer c ON c.id=so.customer_id
               WHERE so.business_id=%s ORDER BY so.id DESC LIMIT 10""",
            (business_id,),
        )
        if not orders:
            bot.send_message(chat_id, "Belum ada Sales Order.\n\nUntuk membuat Sales Order:\n/salesorder buat KODE_PELANGGAN SKU:QTY\nContoh:\n/salesorder buat CUST01 TG-BC-001:5")
            return
        lines = ["📦 DAFTAR SALES ORDER", ""]
        for o in orders:
            lines.append(f"• {o['order_number']} | {o['customer_name']} ({o['customer_code']})")
            lines.append(f"  Total: Rp{int(o['total']):,} | Status: {o['status']}")
            lines.append(f"  Tanggal: {o['order_date']}")
            lines.append("")
        lines.append("Aksi: /salesorder NOMOR | /salesorder buat KODE SKU:QTY")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/salesorder "):
        arg = text[len("/salesorder "):].strip()

        # /salesorder buat KODE_PELANGGAN SKU:QTY [SKU:QTY...]
        if arg.startswith("buat ") or arg == "buat":
            raw = arg[5:].strip() if len(arg) > 4 else ""
            parts = raw.split()
            if len(parts) < 2:
                bot.send_message(chat_id, "Format: /salesorder buat KODE_PELANGGAN SKU:QTY [SKU:QTY...]\nContoh: /salesorder buat CUST01 TG-BC-001:5")
                return

            cust_code = parts[0].upper()
            cust = sales_mod.get_customer(business_id=business_id, code_or_id=cust_code)
            if not cust:
                bot.send_message(chat_id, f"Pelanggan '{cust_code}' tidak ditemukan.")
                return

            items_to_order = []
            for it in parts[1:]:
                if ":" not in it:
                    bot.send_message(chat_id, f"Format item salah: '{it}'. Gunakan SKU:QTY")
                    return
                sku_p, qty_p = it.split(":", 1)
                try:
                    qty_val = int(qty_p)
                except ValueError:
                    bot.send_message(chat_id, f"Jumlah '{qty_p}' harus berupa angka bulat.")
                    return
                items_to_order.append({"sku": sku_p.strip(), "quantity": qty_val})

            try:
                from ..persistence.db import ambil
                preview_lines = [
                    "📦 DRAFT SALES ORDER",
                    "",
                    f"Pelanggan: {cust['name']} ({cust['code']})",
                    "",
                    "Item Pesanan:",
                ]
                subtotal = Decimal("0")
                resolved_payload_lines = []
                for it in items_to_order:
                    msku = ambil("SELECT m.id, m.sku, p.name FROM multichannel.master_sku m JOIN multichannel.product p ON p.id=m.product_id WHERE m.sku=%s", (it["sku"],))
                    if not msku:
                        bot.send_message(chat_id, f"SKU '{it['sku']}' tidak ditemukan.")
                        return
                    sp = sales_mod.get_canonical_selling_price(business_id=business_id, master_sku_id=msku["id"])
                    if sp is None:
                        bot.send_message(chat_id, f"Harga jual untuk SKU '{it['sku']}' belum dikonfigurasi.")
                        return
                    line_tot = sp * it["quantity"]
                    subtotal += line_tot
                    preview_lines.append(f"• {msku['name']} ({msku['sku']}) x {it['quantity']} @ Rp{int(sp):,} = Rp{int(line_tot):,}")
                    resolved_payload_lines.append({
                        "master_sku_id": msku["id"],
                        "sku": msku["sku"],
                        "description": msku["name"],
                        "quantity": it["quantity"],
                        "unit_price": float(sp),
                    })

                preview_lines.append("")
                preview_lines.append(f"Total Pesanan: Rp{int(subtotal):,}")
                preview_lines.append("")
                preview_lines.append("Konfirmasi pembuatan draft Sales Order ini?")

                draft = sales_mod.create_sales_draft(
                    draft_type="SALES_ORDER_CREATE",
                    business_id=business_id,
                    owner_id=owner_id,
                    telegram_user_id=user_id,
                    payload={
                        "customer_id": cust["id"],
                        "warehouse_id": warehouse_id,
                        "lines": resolved_payload_lines,
                    },
                )
                tok = draft["draft_token"]
                kb = {
                    "inline_keyboard": [[
                        {"text": "✅ Buat SO", "callback_data": f"sl_confirm:{tok}"},
                        {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                    ]]
                }
                bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
                return
            except Exception as e:
                bot.send_message(chat_id, f"Gagal membuat draft SO: {e}")
                return

        # /salesorder konfirmasi NOMOR
        if arg.startswith("konfirmasi ") or arg == "konfirmasi":
            so_num = arg[11:].strip() if len(arg) > 10 else ""
            if not so_num:
                bot.send_message(chat_id, "Format: /salesorder konfirmasi NOMOR_SO")
                return

            so = sales_mod.get_sales_order(business_id=business_id, order_number=so_num)
            if not so:
                bot.send_message(chat_id, f"Sales Order '{so_num}' tidak ditemukan.")
                return

            # Check credit limit preview
            exp = sales_mod.get_customer_ar_exposure(business_id=business_id, customer_id=so["customer_id"])
            if exp["credit_limit"] > 0 and (exp["ar_outstanding"] + Decimal(str(so["total"])) > exp["credit_limit"]):
                bot.send_message(
                    chat_id,
                    f"❌ Tidak dapat dikonfirmasi: Batas kredit pelanggan '{so['customer_code']}' terlampaui.\n"
                    f"Batas: Rp{int(exp['credit_limit']):,}\n"
                    f"Piutang saat ini: Rp{int(exp['ar_outstanding']):,}\n"
                    f"Total pesanan ini: Rp{int(so['total']):,}"
                )
                return

            draft = sales_mod.create_sales_draft(
                draft_type="SALES_ORDER_CONFIRM",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"order_number": so_num},
            )
            preview_lines = [
                "✅ KONFIRMASI SALES ORDER",
                "",
                f"Nomor: {so_num}",
                f"Pelanggan: {so['customer_name']} ({so['customer_code']})",
                f"Total: Rp{int(so['total']):,}",
                "",
                "Konfirmasi pesanan ini menjadi komitmen penjualan resmi?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Konfirmasi SO", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # /salesorder batal NOMOR
        if arg.startswith("batal ") or arg == "batal":
            so_num = arg[6:].strip() if len(arg) > 5 else ""
            if not so_num:
                bot.send_message(chat_id, "Format: /salesorder batal NOMOR_SO")
                return

            draft = sales_mod.create_sales_draft(
                draft_type="SALES_ORDER_CANCEL",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"order_number": so_num},
            )
            preview_lines = [
                "❌ BATALKAN SALES ORDER",
                "",
                f"Nomor: {so_num}",
                "",
                "Batalkan Sales Order ini?",
            ]
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Batalkan", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # Detail view /salesorder NOMOR
        so = sales_mod.get_sales_order(business_id=business_id, order_number=arg)
        if not so:
            bot.send_message(chat_id, f"Sales Order '{arg}' tidak ditemukan.")
            return

        lines = [
            f"📦 DETAIL SALES ORDER: {so['order_number']}",
            "",
            f"Pelanggan: {so['customer_name']} ({so['customer_code']})",
            f"Gudang: {so['warehouse_name']}",
            f"Tanggal: {so['order_date']}",
            f"Status: {so['status']}",
            "",
            "Item Pesanan:",
        ]
        for l in so.get("lines", []):
            lines.append(f"• {l['description']} ({l['sku']})")
            lines.append(f"  Pesan: {l['ordered_qty']} | Terkirim: {l['delivered_qty']} | Ditagih: {l['invoiced_qty']}")
            lines.append(f"  @ Rp{int(l['unit_price']):,} = Rp{int(l['line_total']):,}")
        lines.append("")
        lines.append(f"Total: Rp{int(so['total']):,}")

        if so["status"] == "DRAFT":
            lines.append("\nAksi: /salesorder konfirmasi " + so["order_number"] + " | /salesorder batal " + so["order_number"])
        elif so["status"] in ("CONFIRMED", "PARTIALLY_DELIVERED"):
            lines.append("\nAksi: /kirimpesanan " + so["order_number"] + " | /invoice buat " + so["order_number"])

        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # ------------------------------------------------------------
    # /kirimpesanan: SALES DELIVERY
    # ------------------------------------------------------------
    if text in ("/kirimpesanan", "/kirimpesanan@"):
        from ..persistence.db import semua
        pending_so = semua(
            """SELECT so.*, c.name AS customer_name, c.code AS customer_code
               FROM local_business.sales_order so
               JOIN local_business.customer c ON c.id=so.customer_id
               WHERE so.business_id=%s AND so.status IN ('CONFIRMED', 'PARTIALLY_DELIVERED')
               ORDER BY so.id DESC""",
            (business_id,),
        )
        if not pending_so:
            bot.send_message(chat_id, "Tidak ada pesanan yang menunggu pengiriman.\n\nGunakan /salesorder untuk melihat status pesanan.")
            return
        lines = ["🚚 PESANAN MENUNGGU PENGIRIMAN", ""]
        for o in pending_so:
            lines.append(f"• {o['order_number']} | {o['customer_name']} ({o['customer_code']})")
            lines.append(f"  Status: {o['status']} | Total: Rp{int(o['total']):,}")
            lines.append("")
        lines.append("Aksi:\n/kirimpesanan NOMOR_SO (kirim semua)\n/kirimpesanan NOMOR_SO SKU:QTY (kirim sebagian)")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/kirimpesanan "):
        raw_args = text[len("/kirimpesanan "):].strip().split()
        if not raw_args:
            bot.send_message(chat_id, "Format: /kirimpesanan NOMOR_SO [SKU:QTY...]\nContoh: /kirimpesanan BC-SO-2026-000001")
            return

        so_num = raw_args[0]
        so = sales_mod.get_sales_order(business_id=business_id, order_number=so_num)
        if not so:
            bot.send_message(chat_id, f"Sales Order '{so_num}' tidak ditemukan.")
            return

        if so["status"] not in ("CONFIRMED", "PARTIALLY_DELIVERED"):
            bot.send_message(chat_id, f"Sales Order {so_num} status {so['status']} tidak dapat dikirim.")
            return

        lines_to_deliver = []
        if len(raw_args) > 1:
            for it in raw_args[1:]:
                if ":" not in it:
                    bot.send_message(chat_id, f"Format item salah: '{it}'. Gunakan SKU:QTY")
                    return
                sku_p, qty_p = it.split(":", 1)
                lines_to_deliver.append({"sku": sku_p.strip(), "quantity": int(qty_p)})
        else:
            for l in so.get("lines", []):
                rem = l["ordered_qty"] - l["delivered_qty"]
                if rem > 0:
                    lines_to_deliver.append({"master_sku_id": l["master_sku_id"], "sku": l["sku"], "quantity": rem})

        if not lines_to_deliver:
            bot.send_message(chat_id, f"Semua item dalam Sales Order {so_num} sudah terkirim lengkap.")
            return

        preview_lines = [
            "🚚 PENGIRIMAN PESANAN PENJUALAN",
            "",
            f"Sales Order: {so['order_number']}",
            f"Pelanggan: {so['customer_name']} ({so['customer_code']})",
            f"Gudang: {so['warehouse_name']}",
            "",
            "Item yang Dikirim:",
        ]
        for it in lines_to_deliver:
            preview_lines.append(f"• {it.get('sku')} x {it['quantity']}")

        preview_lines.append("")
        preview_lines.append("Dampak Inventaris:")
        preview_lines.append("• Stok fisik (on_hand) akan berkurang sesuai kuantitas kirim.")
        preview_lines.append("")
        preview_lines.append("Konfirmasi pengiriman barang ini?")

        draft = sales_mod.create_sales_draft(
            draft_type="SALES_ORDER_DELIVER",
            business_id=business_id,
            owner_id=owner_id,
            telegram_user_id=user_id,
            payload={
                "order_number": so_num,
                "lines": lines_to_deliver,
            },
        )
        tok = draft["draft_token"]
        kb = {
            "inline_keyboard": [[
                {"text": "✅ Kirim Barang", "callback_data": f"sl_confirm:{tok}"},
                {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
            ]]
        }
        bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
        return

    # ------------------------------------------------------------
    # /invoice: CUSTOMER INVOICE
    # ------------------------------------------------------------
    if text in ("/invoice", "/invoice@"):
        from ..persistence.db import semua
        invoices = semua(
            """SELECT inv.*, c.name AS customer_name, c.code AS customer_code
               FROM local_business.customer_invoice inv
               JOIN local_business.customer c ON c.id=inv.customer_id
               WHERE inv.business_id=%s ORDER BY inv.id DESC LIMIT 10""",
            (business_id,),
        )
        if not invoices:
            bot.send_message(chat_id, "Belum ada Customer Invoice.\n\nUntuk membuat invoice dari Sales Order:\n/invoice buat NOMOR_SO")
            return
        lines = ["🧾 DAFTAR CUSTOMER INVOICE", ""]
        for inv in invoices:
            lines.append(f"• {inv['invoice_number']} | {inv['customer_name']} ({inv['customer_code']})")
            lines.append(f"  Total: Rp{int(inv['total']):,} | Sisa: Rp{int(inv['outstanding_amount']):,}")
            lines.append(f"  Jatuh Tempo: {inv['due_date']} | Status: {inv['status']}")
            lines.append("")
        lines.append("Aksi: /invoice NOMOR | /invoice buat NOMOR_SO | /invoice posting NOMOR")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    if text.startswith("/invoice "):
        arg = text[len("/invoice "):].strip()

        # /invoice buat NOMOR_SO
        if arg.startswith("buat ") or arg == "buat":
            so_num = arg[5:].strip() if len(arg) > 4 else ""
            if not so_num:
                bot.send_message(chat_id, "Format: /invoice buat NOMOR_SO\nContoh: /invoice buat BC-SO-2026-000001")
                return

            so = sales_mod.get_sales_order(business_id=business_id, order_number=so_num)
            if not so:
                bot.send_message(chat_id, f"Sales Order '{so_num}' tidak ditemukan.")
                return

            uninvoiced = []
            subtotal = Decimal("0")
            for l in so.get("lines", []):
                rem = l["delivered_qty"] - l["invoiced_qty"]
                if rem > 0:
                    ltot = Decimal(str(l["unit_price"])) * rem
                    subtotal += ltot
                    uninvoiced.append({
                        "sku": l["sku"],
                        "description": l["description"],
                        "quantity": rem,
                        "unit_price": float(l["unit_price"]),
                        "line_total": float(ltot),
                    })

            if not uninvoiced:
                bot.send_message(chat_id, f"Tidak ada item terkirim yang belum ditagih untuk SO {so_num}. Pastikan barang sudah dikirim via /kirimpesanan.")
                return

            preview_lines = [
                "🧾 DRAFT CUSTOMER INVOICE",
                "",
                f"Sales Order: {so['order_number']}",
                f"Pelanggan: {so['customer_name']} ({so['customer_code']})",
                "",
                "Item Tagihan (Berdasarkan Kuantitas Terkirim):",
            ]
            for it in uninvoiced:
                preview_lines.append(f"• {it['description']} ({it['sku']}) x {it['quantity']} @ Rp{int(it['unit_price']):,} = Rp{int(it['line_total']):,}")

            preview_lines.append("")
            preview_lines.append(f"Total Tagihan: Rp{int(subtotal):,}")
            preview_lines.append("")
            preview_lines.append("Buat draft invoice ini?")

            draft = sales_mod.create_sales_draft(
                draft_type="CUSTOMER_INVOICE_CREATE",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={
                    "customer_id": so["customer_id"],
                    "sales_order_id": so["id"],
                },
            )
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Buat Invoice", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # /invoice posting NOMOR_INVOICE
        if arg.startswith("posting ") or arg == "posting":
            inv_num = arg[8:].strip() if len(arg) > 7 else ""
            if not inv_num:
                bot.send_message(chat_id, "Format: /invoice posting NOMOR_INVOICE\nContoh: /invoice posting BC-CI-2026-000001")
                return

            cinv = sales_mod.get_customer_invoice(business_id=business_id, invoice_number=inv_num)
            if not cinv:
                bot.send_message(chat_id, f"Customer Invoice '{inv_num}' tidak ditemukan.")
                return

            if cinv["status"] != "DRAFT":
                bot.send_message(chat_id, f"Invoice {inv_num} status {cinv['status']} sudah diposting sebelumnya.")
                return

            preview_lines = [
                "📤 POSTING CUSTOMER INVOICE",
                "",
                f"Invoice: {cinv['invoice_number']}",
                f"Pelanggan: {cinv['customer_name']} ({cinv['customer_code']})",
                f"Total: Rp{int(cinv['total']):,}",
                "",
                "Dampak Akuntansi Keuangan:",
                f"• Dr Piutang Usaha (1201): Rp{int(cinv['total']):,}",
                f"• Cr Penjualan (4101): Rp{int(cinv['total']):,}",
                "",
                "Posting invoice ini ke Buku Besar & Piutang Usaha?",
            ]
            draft = sales_mod.create_sales_draft(
                draft_type="CUSTOMER_INVOICE_POST",
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                payload={"invoice_number": inv_num},
            )
            tok = draft["draft_token"]
            kb = {
                "inline_keyboard": [[
                    {"text": "✅ Posting Sekarang", "callback_data": f"sl_confirm:{tok}"},
                    {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
                ]]
            }
            bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
            return

        # Detail view /invoice NOMOR
        cinv = sales_mod.get_customer_invoice(business_id=business_id, invoice_number=arg)
        if not cinv:
            bot.send_message(chat_id, f"Customer Invoice '{arg}' tidak ditemukan.")
            return

        lines = [
            f"🧾 DETAIL CUSTOMER INVOICE: {cinv['invoice_number']}",
            "",
            f"Pelanggan: {cinv['customer_name']} ({cinv['customer_code']})",
            f"Sales Order: {cinv.get('order_number') or '-'}",
            f"Tanggal: {cinv['invoice_date']}",
            f"Jatuh Tempo: {cinv['due_date']}",
            f"Status: {cinv['status']}",
            "",
            "Item:",
        ]
        for l in cinv.get("lines", []):
            lines.append(f"• {l['description']} ({l['sku']}) x {l['quantity']} @ Rp{int(l['unit_price']):,} = Rp{int(l['line_total']):,}")
        lines.append("")
        lines.append(f"Total: Rp{int(cinv['total']):,}")
        lines.append(f"Sudah Dibayar: Rp{int(cinv['paid_amount']):,}")
        lines.append(f"Sisa Piutang: Rp{int(cinv['outstanding_amount']):,}")

        if cinv["status"] == "DRAFT":
            lines.append("\nAksi: /invoice posting " + cinv["invoice_number"])
        elif cinv["status"] in ("POSTED", "PARTIALLY_PAID"):
            lines.append("\nAksi: /terimabayar " + cinv["invoice_number"] + " " + str(int(cinv["outstanding_amount"])))

        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # ------------------------------------------------------------
    # /piutang: AR AGING & OUTSTANDING REPORT
    # ------------------------------------------------------------
    if text in ("/piutang", "/piutang@") or text.startswith("/piutang "):
        cust_arg = text[len("/piutang "):].strip() if text.startswith("/piutang ") else None
        aging = sales_mod.get_ar_aging(business_id=business_id, customer_code=cust_arg)

        lines = [
            "📊 LAPORAN UMUR PIUTANG (AR AGING)",
            f"Per Tanggal: {aging['as_of_date']}",
            "",
            f"Total Piutang Berjalan: Rp{int(aging['total_outstanding']):,}",
            "",
            "Rincian Berdasarkan Umur:",
            f"• Belum Jatuh Tempo (Current): Rp{int(aging['buckets']['CURRENT']):,}",
            f"• Lewat 1 - 30 Hari: Rp{int(aging['buckets']['1_30']):,}",
            f"• Lewat 31 - 60 Hari: Rp{int(aging['buckets']['31_60']):,}",
            f"• Lewat 61 - 90 Hari: Rp{int(aging['buckets']['61_90']):,}",
            f"• Lewat > 90 Hari: Rp{int(aging['buckets']['OVER_90']):,}",
            "",
        ]

        if aging["invoices"]:
            lines.append("Daftar Invoice Belum Lunas:")
            for inv_item in aging["invoices"][:10]:
                od_str = f"Lewat {inv_item['days_overdue']} hr" if inv_item['days_overdue'] > 0 else "Belum jatuh tempo"
                lines.append(f"• {inv_item['invoice_number']} | {inv_item['customer_name']}")
                lines.append(f"  Sisa: Rp{int(inv_item['outstanding_amount']):,} | {od_str} (Jatuh tempo: {inv_item['due_date']})")
                lines.append("")
            lines.append("Aksi: /terimabayar NOMOR_INVOICE JUMLAH")
        else:
            lines.append("Tidak ada piutang outstanding. Semua invoice telah lunas!")

        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # ------------------------------------------------------------
    # /terimabayar: CUSTOMER PAYMENT
    # ------------------------------------------------------------
    if text in ("/terimabayar", "/terimabayar@"):
        bot.send_message(
            chat_id,
            "Format penerimaan pembayaran:\n"
            "/terimabayar NOMOR_INVOICE JUMLAH\n"
            "/terimabayar NOMOR_INVOICE JUMLAH BANK\n\n"
            "Contoh:\n"
            "/terimabayar BC-CI-2026-000001 500000\n"
            "/terimabayar BC-CI-2026-000001 500000 BANK"
        )
        return

    if text.startswith("/terimabayar "):
        raw_args = text[len("/terimabayar "):].strip().split()
        if len(raw_args) < 2:
            bot.send_message(chat_id, "Format: /terimabayar NOMOR_INVOICE JUMLAH [KAS|BANK]\nContoh: /terimabayar BC-CI-2026-000001 500000")
            return

        inv_num = raw_args[0]
        try:
            pay_amount = Decimal(raw_args[1].replace(".", "").replace(",", "."))
        except Exception:
            bot.send_message(chat_id, "Jumlah pembayaran tidak valid.")
            return

        if pay_amount <= 0:
            bot.send_message(chat_id, "Jumlah pembayaran harus lebih besar dari 0.")
            return

        acc_choice = raw_args[2].upper() if len(raw_args) > 2 else "1101"
        acc_label = "Bank (1102)" if acc_choice in ("1102", "BANK", "TRANSFER") else "Kas (1101)"

        cinv = sales_mod.get_customer_invoice(business_id=business_id, invoice_number=inv_num)
        if not cinv:
            bot.send_message(chat_id, f"Customer Invoice '{inv_num}' tidak ditemukan.")
            return

        if cinv["status"] not in ("POSTED", "PARTIALLY_PAID"):
            bot.send_message(chat_id, f"Invoice {inv_num} status {cinv['status']} tidak dapat menerima pembayaran.")
            return

        outstanding = Decimal(str(cinv["outstanding_amount"]))
        if pay_amount > outstanding:
            bot.send_message(chat_id, f"Jumlah bayar (Rp{int(pay_amount):,}) melebihi sisa piutang (Rp{int(outstanding):,}).")
            return

        remaining_after = outstanding - pay_amount

        draft = sales_mod.create_sales_draft(
            draft_type="CUSTOMER_PAYMENT",
            business_id=business_id,
            owner_id=owner_id,
            telegram_user_id=user_id,
            payload={
                "invoice_number": inv_num,
                "amount": float(pay_amount),
                "payment_account_id": acc_choice,
            },
        )

        preview_lines = [
            "💳 PENERIMAAN PEMBAYARAN PIUTANG",
            "",
            f"Invoice: {cinv['invoice_number']}",
            f"Pelanggan: {cinv['customer_name']} ({cinv['customer_code']})",
            f"Total Invoice: Rp{int(cinv['total']):,}",
            f"Sudah Dibayar: Rp{int(cinv['paid_amount']):,}",
            f"Sisa Piutang: Rp{int(outstanding):,}",
            "",
            f"Pembayaran Diterima: Rp{int(pay_amount):,}",
            f"Sisa Setelah Bayar: Rp{int(remaining_after):,}",
            f"Akun Penerimaan: {acc_label}",
            "",
            "Dampak Akuntansi Keuangan:",
            f"• Dr {acc_label}: Rp{int(pay_amount):,}",
            f"• Cr Piutang Usaha (1201): Rp{int(pay_amount):,}",
            "",
            "Konfirmasi penerimaan pembayaran ini?",
        ]

        tok = draft["draft_token"]
        kb = {
            "inline_keyboard": [[
                {"text": "✅ Terima Bayar", "callback_data": f"sl_confirm:{tok}"},
                {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
            ]]
        }
        bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
        return

    # ------------------------------------------------------------
    # /returjual: CUSTOMER RETURN & CREDIT NOTE
    # ------------------------------------------------------------
    if text in ("/returjual", "/returjual@"):
        bot.send_message(
            chat_id,
            "Format retur penjualan:\n"
            "/returjual NOMOR_SO SKU:QTY [ALASAN]\n\n"
            "Contoh:\n"
            "/returjual BC-SO-2026-000001 TG-BC-001:2 Rusak dalam pengiriman"
        )
        return

    if text.startswith("/returjual "):
        raw_args = text[len("/returjual "):].strip().split(maxsplit=2)
        if len(raw_args) < 2:
            bot.send_message(chat_id, "Format: /returjual NOMOR_SO SKU:QTY [ALASAN]\nContoh: /returjual BC-SO-2026-000001 TG-BC-001:2")
            return

        so_num = raw_args[0]
        sku_qty_str = raw_args[1]
        reason_str = raw_args[2] if len(raw_args) > 2 else "Retur barang"

        if ":" not in sku_qty_str:
            bot.send_message(chat_id, "Format item salah. Gunakan SKU:QTY (contoh: TG-BC-001:2)")
            return

        sku_p, qty_p = sku_qty_str.split(":", 1)
        try:
            qty_val = int(qty_p)
        except ValueError:
            bot.send_message(chat_id, "Jumlah retur harus bilangan bulat.")
            return

        so = sales_mod.get_sales_order(business_id=business_id, order_number=so_num)
        if not so:
            bot.send_message(chat_id, f"Sales Order '{so_num}' tidak ditemukan.")
            return

        draft = sales_mod.create_sales_draft(
            draft_type="SALES_RETURN_CREATE",
            business_id=business_id,
            owner_id=owner_id,
            telegram_user_id=user_id,
            payload={
                "order_number": so_num,
                "lines": [{"sku": sku_p.strip(), "quantity": qty_val}],
                "reason": reason_str,
            },
        )

        preview_lines = [
            "🔄 RETUR PENJUALAN & NOTA KREDIT",
            "",
            f"Sales Order: {so['order_number']}",
            f"Pelanggan: {so['customer_name']} ({so['customer_code']})",
            f"Item Retur: {sku_p} x {qty_val}",
            f"Alasan: {reason_str}",
            "",
            "Dampak:",
            "• Stok fisik barang akan dikembalikan ke gudang.",
            "• Nota kredit (Credit Note) akan dibuat dan mengurangi tagihan invoice terkait.",
            "",
            "Konfirmasi retur penjualan ini?",
        ]

        tok = draft["draft_token"]
        kb = {
            "inline_keyboard": [[
                {"text": "✅ Proses Retur", "callback_data": f"sl_confirm:{tok}"},
                {"text": "❌ Batal", "callback_data": f"sl_cancel:{tok}"},
            ]]
        }
        bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
        return

    # ============================================================
    # UMKM ESSENTIAL DAILY OPERATIONS
    # ============================================================

    # /keluar JUMLAH|KETERANGAN|KATEGORI[|SUMBER]
    if text.startswith("/keluar"):
        rest = text[len("/keluar"):].strip()
        if not rest:
            bot.send_message(
                chat_id,
                "Format: /keluar JUMLAH|KETERANGAN|KATEGORI\n"
                "  atau: /keluar JUMLAH|KETERANGAN|KATEGORI|BANK\n\n"
                "Contoh:\n"
                "/keluar 50000|Bensin motor|transport\n"
                "/keluar 200000|Bayar listrik|listrik|bank\n\n"
                "Kategori: transport, listrik, sewa, internet, gaji, makan, "
                "operasional, marketing, perbaikan, lainnya",
            )
            return

        fields = [f.strip() for f in rest.split("|")]
        if len(fields) < 3:
            bot.send_message(
                chat_id,
                "Format: /keluar JUMLAH|KETERANGAN|KATEGORI[|KAS atau BANK]\n"
                "Contoh: /keluar 50000|Bensin motor|transport",
            )
            return

        raw_amt = fields[0].replace(".", "").replace(",", "").replace("Rp", "").replace("rp", "").strip()
        try:
            from decimal import Decimal
            amount = Decimal(raw_amt)
            if amount <= Decimal("0"):
                bot.send_message(chat_id, "❌ Jumlah pengeluaran harus lebih besar dari 0.")
                return
        except Exception:
            bot.send_message(chat_id, f"❌ Jumlah '{fields[0]}' tidak valid.")
            return

        description = fields[1]
        category_input = fields[2]
        payment_src_input = fields[3] if len(fields) > 3 else "kas"

        try:
            draft = umkm_mod.create_expense_draft(
                business_id=business_id,
                owner_id=owner_id,
                telegram_user_id=user_id,
                amount=amount,
                description=description,
                category=category_input,
                payment_source=payment_src_input,
            )
        except ValueError as e:
            bot.send_message(chat_id, f"❌ {e}")
            return

        preview_lines = [
            "💸 KONFIRMASI PENGELUARAN",
            "",
            f"Jumlah: Rp{int(amount):,}",
            f"Keterangan: {description}",
            f"Kategori: {draft['category_label']} ({draft['category']})",
            f"Sumber Dana: {draft['payment_source']}",
            "",
            "Simpan pengeluaran ini?",
        ]
        tok = draft["draft_token"]
        kb = {
            "inline_keyboard": [[
                {"text": "✅ Simpan", "callback_data": f"exp_confirm:{tok}"},
                {"text": "❌ Batal", "callback_data": f"exp_cancel:{tok}"},
            ]]
        }
        bot.send_message(chat_id, "\n".join(preview_lines).strip(), reply_markup=kb)
        return

    # /pengeluaran [hariini|bulanini|YYYY-MM]
    if text.startswith("/pengeluaran") or text in ("/pengeluaran", "/pengeluaran@"):
        from datetime import date
        import calendar
        rest = text[len("/pengeluaran"):].strip()
        today = date.today()

        if not rest or rest in ("hariini", "hari ini"):
            start_date = today
            end_date = today
            label = f"Hari ini ({today.isoformat()})"
        elif rest in ("bulanini", "bulan ini"):
            _, last_day = calendar.monthrange(today.year, today.month)
            start_date = date(today.year, today.month, 1)
            end_date = date(today.year, today.month, last_day)
            label = f"Bulan ini ({today.strftime('%B %Y')})"
        else:
            try:
                parts_date = rest.split("-")
                yr = int(parts_date[0])
                mo = int(parts_date[1])
                _, last_day = calendar.monthrange(yr, mo)
                start_date = date(yr, mo, 1)
                end_date = date(yr, mo, last_day)
                label = f"{yr}-{mo:02d}"
            except Exception:
                bot.send_message(chat_id, "Format: /pengeluaran, /pengeluaran hariini, /pengeluaran bulanini, atau /pengeluaran YYYY-MM")
                return

        exp_data = umkm_mod.get_expenses(business_id=business_id, start_date=start_date, end_date=end_date)

        if not exp_data["expenses"]:
            bot.send_message(chat_id, f"📋 Tidak ada pengeluaran tercatat untuk {label}.")
            return

        lines = [f"💸 PENGELUARAN — {label}", ""]
        for cat, total in sorted(exp_data["by_category"].items(), key=lambda x: -x[1]):
            lines.append(f"• {cat}: Rp{int(total):,}")
        lines.append("")
        lines.append(f"Total: Rp{int(exp_data['total_amount']):,}")
        lines.append(f"({len(exp_data['expenses'])} transaksi)")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # /kas
    if text in ("/kas", "/kas@"):
        try:
            cb = umkm_mod.get_cash_bank_balances(business_id=business_id)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Gagal membaca saldo kas/bank: {e}")
            return

        lines = [
            "💰 SALDO KAS & BANK",
            "",
            f"Kas (1101):   Rp{int(cb['kas']):,}",
            f"Bank (1102):  Rp{int(cb['bank']):,}",
            "",
            f"Total Likuid: Rp{int(cb['total']):,}",
        ]
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # /labarugi [YYYY-MM]
    if text.startswith("/labarugi") or text in ("/labarugi", "/labarugi@"):
        from datetime import date
        import calendar
        rest = text[len("/labarugi"):].strip()
        today = date.today()

        if not rest:
            _, last_day = calendar.monthrange(today.year, today.month)
            start_date = date(today.year, today.month, 1)
            end_date = today
            label = f"Bulan ini ({today.strftime('%B %Y')})"
        else:
            try:
                parts_date = rest.split("-")
                yr = int(parts_date[0])
                mo = int(parts_date[1])
                _, last_day = calendar.monthrange(yr, mo)
                start_date = date(yr, mo, 1)
                end_date = date(yr, mo, last_day)
                label = f"{yr}-{mo:02d}"
            except Exception:
                bot.send_message(chat_id, "Format: /labarugi atau /labarugi YYYY-MM")
                return

        try:
            pl = umkm_mod.get_profit_loss(business_id=business_id, date_from=start_date, date_to=end_date)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Gagal membaca laporan laba rugi: {e}")
            return

        net = pl["net_income"]
        sign = "📈" if net >= 0 else "📉"
        lines = [
            f"{sign} LABA RUGI — {label}",
            "",
            f"Pendapatan:        Rp{int(pl['revenue']):,}",
            f"HPP (Harga Pokok): Rp{int(pl['hpp']):,}",
            f"Laba Kotor:        Rp{int(pl['gross_profit']):,}",
            f"Beban Operasional: Rp{int(pl['operational_expenses']):,}",
            "",
            f"Laba Bersih:       Rp{int(net):,}",
        ]
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # /ringkasan
    if text in ("/ringkasan", "/ringkasan@"):
        try:
            s = umkm_mod.get_business_summary(business_id=business_id)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Gagal membuat ringkasan: {e}")
            return

        td = s["today"]
        fi = s["finance"]
        inv = s["inventory"]
        mtd = s["month_to_date"]
        net_icon = "📈" if mtd["net_income"] >= 0 else "📉"

        lines = [
            "📊 RINGKASAN BISNIS HARI INI",
            f"({s['target_date']})",
            "",
            "— Hari Ini —",
            f"Penjualan:   Rp{int(td['sales_amount']):,} ({td['transaction_count']} transaksi)",
            f"Pengeluaran: Rp{int(td['expense_amount']):,}",
            "",
            "— Kas & Bank —",
            f"Kas:  Rp{int(fi['kas']):,}",
            f"Bank: Rp{int(fi['bank']):,}",
            f"Total Likuid: Rp{int(fi['total_liquid']):,}",
            "",
            "— Piutang & Utang —",
            f"Piutang (AR): Rp{int(fi['ar_outstanding']):,}",
            f"Utang (AP):   Rp{int(fi['ap_outstanding']):,}",
            "",
            "— Inventaris —",
            f"Stok menipis: {inv['low_stock_count']} produk",
            f"Perlu restock: {inv['reorder_count']} produk",
            "",
            f"— MTD {mtd['period']} —",
            f"Pendapatan: Rp{int(mtd['revenue']):,}",
            f"Beban:      Rp{int(mtd['expense']):,}",
            f"Laba Bersih: {net_icon} Rp{int(mtd['net_income']):,}",
        ]
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # /posisi
    if text in ("/posisi", "/posisi@"):
        try:
            pos = umkm_mod.get_financial_position(business_id=business_id)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Gagal membaca posisi keuangan: {e}")
            return

        bal_icon = "✅" if pos["balanced"] else "⚠️"
        lines = [
            f"📋 POSISI KEUANGAN — Per {pos['as_of']}",
            "",
            "ASET:",
        ]
        for name, bal in pos["assets"].items():
            lines.append(f"  {name}: Rp{int(bal):,}")
        lines.append(f"Total Aset: Rp{int(pos['total_assets']):,}")
        lines.append("")
        lines.append("KEWAJIBAN:")
        for name, bal in pos["liabilities"].items():
            lines.append(f"  {name}: Rp{int(bal):,}")
        lines.append(f"Total Kewajiban: Rp{int(pos['total_liabilities']):,}")
        lines.append("")
        eq = pos["equity"]
        lines.append("EKUITAS:")
        lines.append(f"  Modal: Rp{int(eq['modal']):,}")
        lines.append(f"  Laba Berjalan: Rp{int(eq['laba_berjalan']):,}")
        lines.append(f"Total Ekuitas: Rp{int(eq['total_equity']):,}")
        lines.append("")
        lines.append(f"{bal_icon} Neraca {'seimbang' if pos['balanced'] else 'TIDAK SEIMBANG'}")
        bot.send_message(chat_id, "\n".join(lines).strip())
        return

    # /export [YYYY-MM]
    if text.startswith("/export") or text in ("/export", "/export@"):
        from datetime import date
        rest = text[len("/export"):].strip()
        today = date.today()

        if not rest:
            yr, mo = today.year, today.month
        else:
            try:
                parts_date = rest.split("-")
                yr = int(parts_date[0])
                mo = int(parts_date[1])
            except Exception:
                bot.send_message(chat_id, "Format: /export atau /export YYYY-MM")
                return

        bot.send_message(chat_id, f"⏳ Menyiapkan export laporan {yr}-{mo:02d}...")
        try:
            csv_content = umkm_mod.generate_export_csv(business_id=business_id, year=yr, month=mo)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Gagal membuat export: {e}")
            return

        filename = f"laporan_{business_id}_{yr}{mo:02d}.csv"
        try:
            bot.send_document(
                chat_id=chat_id,
                filename=filename,
                content=csv_content.encode("utf-8"),
                caption=f"Laporan Keuangan {yr}-{mo:02d}",
            )
        except Exception:
            # Fallback: send as text if send_document not available
            preview_lines = csv_content.split("\n")[:30]
            bot.send_message(
                chat_id,
                f"📊 Export {yr}-{mo:02d} (30 baris pertama):\n\n" + "\n".join(preview_lines),
            )
        return

    bot.send_message(chat_id, "Gunakan /barang Nama,SKU,Harga,Modal,Stok atau kirim file.")


def _handle_callback(bot, update, ctx: reg.TelegramExecutionContext | None):
    cb = update.get("callback_query") or {}
    cb_id = cb.get("id")
    user_id = (cb.get("from") or {}).get("id", 0)
    data = cb.get("data", "")
    chat = (cb.get("message") or {}).get("chat") or {}
    chat_id = chat.get("id")
    msg = cb.get("message") or {}
    msg_chat = (msg.get("chat") or {}).get("id")
    msg_id = msg.get("message_id")

    # Business context switcher callback
    if data.startswith("biz_switch:"):
        new_biz_id = int(data.split(":", 1)[1])
        res = reg.switch_user_business(user_id, new_biz_id)
        if res.get("ok"):
            bot.answer_callback_query(cb_id, f"Beralih ke {res['business_name']}")
            if msg_chat is not None and msg_id is not None:
                try:
                    bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
                except TelegramError:
                    pass
            bot.send_message(chat_id, f"✅ Bisnis aktif sekarang: *{res['business_name']}*", parse_mode="Markdown")
        else:
            bot.answer_callback_query(cb_id, res.get("error", "Gagal beralih bisnis"))
        return

    # Branch context switcher callback
    if data.startswith("br_switch:"):
        new_br_id = int(data.split(":", 1)[1])
        if not ctx or not ctx.business_id:
            bot.answer_callback_query(cb_id, "Bisnis tidak aktif")
            return
        res = reg.switch_user_branch(user_id, ctx.business_id, new_br_id)
        if res.get("ok"):
            bot.answer_callback_query(cb_id, f"Beralih ke {res['branch_name']}")
            if msg_chat is not None and msg_id is not None:
                try:
                    bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
                except TelegramError:
                    pass
            bot.send_message(chat_id, f"✅ Cabang aktif sekarang: *{res['branch_name']}*", parse_mode="Markdown")
        else:
            bot.answer_callback_query(cb_id, res.get("error", "Gagal beralih cabang"))
        return

    if not ctx or not ctx.business_id:
        bot.answer_callback_query(cb_id, "Akun belum terhubung ke bisnis.")
        return

    business_id = ctx.business_id
    owner_id = ctx.business_id
    branch_id = ctx.branch_id or 0
    warehouse_id = ctx.warehouse_id or 0

    # Sales Order-to-Cash callbacks
    if data.startswith("sl_confirm:"):
        token = data.split(":", 1)[1]
        res = sales_mod.confirm_sales_draft(
            draft_token=token,
            caller_telegram_user_id=user_id,
        )
        if not res.get("ok"):
            bot.answer_callback_query(cb_id, res.get("message", "Gagal mengonfirmasi draft."))
            return

        if res.get("idempotent"):
            bot.answer_callback_query(cb_id, res.get("message", "Draft sudah diproses."))
            return

        bot.answer_callback_query(cb_id, "Operasi berhasil disimpan.")
        if msg_chat is not None and msg_id is not None:
            try:
                bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
            except TelegramError:
                pass

        bot.send_message(chat_id, f"✅ {res['data'].get('message', 'Berhasil diproses.')}")
        return

    if data.startswith("sl_cancel:"):
        token = data.split(":", 1)[1]
        res = sales_mod.cancel_sales_draft(
            draft_token=token,
            caller_telegram_user_id=user_id,
        )
        if res.get("ok"):
            bot.answer_callback_query(cb_id, "Draft dibatalkan.")
            if msg_chat is not None and msg_id is not None:
                try:
                    bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
                except TelegramError:
                    pass
        else:
            bot.answer_callback_query(cb_id, "Tidak dapat membatalkan draft.")
        return

    # Procurement callbacks
    if data.startswith("pc_confirm:"):
        token = data.split(":", 1)[1]
        res = proc_mod.confirm_procurement_draft(
            draft_token=token,
            caller_telegram_user_id=user_id,
        )
        if not res.get("ok"):
            bot.answer_callback_query(cb_id, res.get("message", "Gagal mengonfirmasi draft."))
            return

        if res.get("idempotent"):
            bot.answer_callback_query(cb_id, res.get("message", "Draft sudah diproses."))
            return

        bot.answer_callback_query(cb_id, "Operasi berhasil disimpan.")
        if msg_chat is not None and msg_id is not None:
            try:
                bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
            except TelegramError:
                pass

        bot.send_message(chat_id, f"✅ {res['data'].get('message', 'Berhasil diproses.')}")
        return

    if data.startswith("pc_cancel:"):
        token = data.split(":", 1)[1]
        res = proc_mod.cancel_procurement_draft(
            draft_token=token,
            caller_telegram_user_id=user_id,
        )
        if res.get("ok"):
            bot.answer_callback_query(cb_id, "Draft dibatalkan.")
            if msg_chat is not None and msg_id is not None:
                try:
                    bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
                except TelegramError:
                    pass
        else:
            bot.answer_callback_query(cb_id, res.get("message", "Tidak dapat membatalkan draft."))
        return

    if data.startswith("th_confirm:"):
        token = data.split(":", 1)[1]
        res = low_stock.confirm_threshold_draft(
            draft_token=token,
            telegram_user_id=user_id,
            business_id=business_id,
            owner_id=owner_id,
        )
        if not res.get("ok"):
            reason = {
                "wrong_user": "Anda tidak berhak mengonfirmasi draft ini.",
                "draft_expired": "Draft kedaluwarsa.",
                "draft_cancelled": "Draft sudah dibatalkan.",
                "no_draft": "Draft tidak dikenal.",
                "draft_wrong_business": "Draft bukan milik bisnis Anda.",
            }.get(res.get("error"), "Gagal menyimpan batas stok minimum.")
            bot.answer_callback_query(cb_id, reason)
            return

        if res.get("idempotent"):
            bot.answer_callback_query(cb_id, "Batas stok minimum sudah disimpan.")
            return

        bot.answer_callback_query(cb_id, "Batas stok minimum berhasil disimpan.")
        if msg_chat is not None and msg_id is not None:
            try:
                bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
            except TelegramError:
                pass

        if res.get("action") == "SET":
            bot.send_message(chat_id, f"✅ Batas stok minimum untuk {res['sku']} berhasil diatur ke {res['new_threshold']}.")
        else:
            bot.send_message(chat_id, f"✅ Batas stok minimum untuk {res['sku']} telah dinonaktifkan.")
        return

    if data.startswith("th_cancel:"):
        token = data.split(":", 1)[1]
        res = low_stock.cancel_threshold_draft(
            draft_token=token,
            telegram_user_id=user_id,
            business_id=business_id,
            owner_id=owner_id,
        )
        if res.get("ok"):
            bot.answer_callback_query(cb_id, "Draft dibatalkan.")
            if msg_chat is not None and msg_id is not None:
                try:
                    bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
                except TelegramError:
                    pass
        else:
            reason = {
                "wrong_user": "Anda tidak berhak membatalkan draft ini.",
                "already_confirmed": "Draft sudah dikonfirmasi.",
                "no_draft": "Draft tidak dikenal.",
            }.get(res.get("error"), "Tidak dapat membatalkan draft.")
            bot.answer_callback_query(cb_id, reason)
        return

    if data.startswith("cancel:"):
        batch_id = data.split(":", 1)[1]
        res = ti.cancel_pending(
            batch_id=batch_id, owner_id=owner_id, telegram_user_id=user_id,
            business_id=business_id)
        if res.get("ok") and res.get("cancelled"):
            bot.answer_callback_query(cb_id, "Draft dibatalkan.")
            # Safe markup cleanup only if we can identify the source message.
            if msg_chat is not None and msg_id is not None:
                try:
                    bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
                except TelegramError:
                    pass  # keyboard removal is cosmetic; backend cancel already done
            return
        if res.get("ok") and res.get("idempotent"):
            bot.answer_callback_query(cb_id, "Draft sudah dibatalkan.")
            return
        reason = {
            "unpaired": "Koneksi tidak terhubung.",
            "no_batch": "Batch tidak dikenal.",
            "batch_wrong_business": "Batch bukan milik Anda.",
        }.get(res.get("error"), "Tidak dapat membatalkan draft.")
        bot.answer_callback_query(cb_id, reason)
        return
    if data.startswith("detail:"):
        batch_id = data.split(":", 1)[1]
        pv = intake_mod.preview(batch_id)
        b = pv.get("batch", {})
        bot.answer_callback_query(cb_id,
            f"{b.get('total_rows',0)} baris: {b.get('ready_rows',0)} siap, "
            f"{b.get('warning_rows',0)} perlu, {b.get('rejected_rows',0)} ditolak.")
        return
    if data.startswith("confirm:"):
        batch_id = data.split(":", 1)[1]
        res = ti.confirm_pending(
            batch_id=batch_id, owner_id=owner_id, telegram_user_id=user_id,
            business_id=business_id, tenant_id=f"BIZ-{business_id}",
            branch_id=branch_id, warehouse_id=warehouse_id)
        if res.get("ok"):
            # Truthful completion message reflecting actual committed effects
            # from the canonical result (no fabricated cost claim).
            parts = ["produk"]
            if res.get("committed_price"):
                parts.append("harga")
            if res.get("committed_stock"):
                parts.append("stok")
            if res.get("committed_cost"):
                parts.append("modal")
            done = ", dan ".join(parts) if len(parts) > 1 else parts[0]
            extra = "" if res.get("committed_cost") else " Modal tidak diisi."
            text = f"Import selesai: {done} telah dibuat.{extra}"
            bot.answer_callback_query(cb_id, "Import berhasil dikonfirmasi.")
            # Remove the now-stale inline keyboard after durable success.
            if msg_chat is not None and msg_id is not None:
                try:
                    bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
                except TelegramError:
                    pass  # cosmetic; durable commit already succeeded
            bot.send_message(chat_id, text)
        else:
            bot.answer_callback_query(cb_id, "Tidak dapat mengonfirmasi: " + str(res.get("error", "")))
        return
    # UMKM Expense draft callbacks
    if data.startswith("exp_confirm:"):
        token = data.split(":", 1)[1]
        res = umkm_mod.confirm_expense_draft(
            draft_token=token,
            caller_telegram_user_id=user_id,
        )
        if not res.get("ok"):
            err = res.get("error", "Gagal mengonfirmasi pengeluaran.")
            bot.answer_callback_query(cb_id, err)
            return

        if res.get("already_confirmed"):
            bot.answer_callback_query(cb_id, "Pengeluaran sudah dicatat sebelumnya.")
            return

        bot.answer_callback_query(cb_id, "Pengeluaran berhasil dicatat.")
        if msg_chat is not None and msg_id is not None:
            try:
                bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
            except TelegramError:
                pass

        exp = res["data"]
        bot.send_message(
            chat_id,
            f"✅ Pengeluaran dicatat!\n\n"
            f"No: {exp['expense_number']}\n"
            f"Jumlah: Rp{int(exp['amount']):,}\n"
            f"Kategori: {exp['category']}\n"
            f"Sumber: {exp['payment_source']}\n"
            f"Keterangan: {exp['description']}",
        )
        return

    if data.startswith("exp_cancel:"):
        token = data.split(":", 1)[1]
        res = umkm_mod.cancel_expense_draft(
            draft_token=token,
            caller_telegram_user_id=user_id,
        )
        if res.get("ok"):
            bot.answer_callback_query(cb_id, "Pengeluaran dibatalkan.")
            if msg_chat is not None and msg_id is not None:
                try:
                    bot.edit_message_reply_markup(msg_chat, msg_id, reply_markup={})
                except TelegramError:
                    pass
        else:
            err = res.get("error", "Tidak dapat membatalkan draft pengeluaran.")
            bot.answer_callback_query(cb_id, err)
        return
    bot.answer_callback_query(cb_id, "Perintah tidak dikenal.")


# ============================================================ polling & unified entrypoint
def process_telegram_update(bot: BotApiClient, upd: dict, bot_info: dict | None = None) -> bool:
    """Unified handler for Telegram updates (Polling and BYOB Webhook)."""
    up_id = int(upd.get("update_id", 0))
    if up_id and ti._update_seen(up_id):
        return True  # durable replay protection

    msg = upd.get("message") or upd.get("callback_query", {}).get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id", 0)
    user_id = (upd.get("message", {}).get("from") or upd.get("callback_query", {}).get("from") or {}).get("id", 0)

    ctx = reg.resolve_execution_context(user_id, chat_id, bot_info)

    try:
        if "message" in upd:
            if up_id:
                ti.record_update(update_id=up_id, chat_id=chat_id, telegram_user_id=user_id,
                                 kind="MESSAGE", file_unique_id="")
            _handle_message(bot, upd, ctx)
        elif "callback_query" in upd:
            if up_id:
                ti.record_update(update_id=up_id, chat_id=chat_id, telegram_user_id=user_id,
                                 kind="CALLBACK")
            _handle_callback(bot, upd, ctx)
        return True
    except Exception as e:
        log.exception("handler error: %s", e)
        return False


def _poll_once(bot: BotApiClient, offset: int) -> int:
    try:
        updates = bot.get_updates(offset=offset, timeout=30)
    except TelegramError as e:
        log.warning("getUpdates error: %s", e)
        return offset
    next_offset = offset
    for upd in updates or []:
        next_offset = max(next_offset, int(upd["update_id"]) + 1)
        process_telegram_update(bot, upd)
    return next_offset


def run(once: bool = False) -> int:
    token = _token()
    if not token:
        log.warning("TELEGRAM_REAL_CONNECTIVITY=BLOCKED_EXTERNAL_TOKEN (no dedicated token)")
        return 0
    bot = BotApiClient(token)
    me = bot.get_me()
    log.info("getMe ok: @%s", me.get("username", "?"))
    wh = bot.get_webhook_info()
    if wh.get("url"):
        log.warning("TELEGRAM_EXISTING_WEBHOOK=DETECTED url=%s; poller stopped until reconciled", wh.get("url"))
        return 2

    # Reconcile command menu with Telegram
    try:
        bot.set_my_commands([
            {"command": "start", "description": "Mulai / hubungkan akun"},
            {"command": "help", "description": "Bantuan perintah"},
            {"command": "status", "description": "Status koneksi & bisnis aktif"},
            {"command": "bisnis", "description": "Ganti bisnis aktif"},
            {"command": "cabang", "description": "Ganti cabang aktif"},
            {"command": "unpair", "description": "Putuskan koneksi Telegram"},
            {"command": "barang", "description": "Input produk baru"},
            {"command": "barcode", "description": "Input atau cari barcode"},
            {"command": "stokminimum", "description": "Atur batas stok minimum"},
            {"command": "stokrendah", "description": "Lihat produk stok menipis"},
            {"command": "supplier", "description": "Kelola supplier"},
            {"command": "restockconfig", "description": "Konfigurasi restock SKU"},
            {"command": "reorder", "description": "Rekomendasi restock inventaris"},
            {"command": "po", "description": "Purchase order"},
            {"command": "terimapo", "description": "Terima barang dari PO"},
            {"command": "tagihan", "description": "Tagihan supplier"},
            {"command": "bayar", "description": "Pembayaran tagihan"},
            {"command": "keluar", "description": "Catat pengeluaran harian"},
            {"command": "pengeluaran", "description": "Laporan pengeluaran"},
            {"command": "kas", "description": "Saldo kas & bank"},
            {"command": "labarugi", "description": "Laporan laba rugi"},
            {"command": "ringkasan", "description": "Ringkasan bisnis hari ini"},
            {"command": "posisi", "description": "Posisi keuangan (neraca)"},
            {"command": "export", "description": "Export laporan CSV"},
        ])
    except Exception as e:
        log.warning("setMyCommands warning: %s", e)

    offset = ti.current_offset()
    while True:
        offset = _poll_once(bot, offset)
        ti.save_offset(offset)
        if once:
            return 0
        time.sleep(0.3)


if __name__ == "__main__":
    import time
    once = os.environ.get("BC_BISNIS_TELEGRAM_ONCE", "0") == "1"
    raise SystemExit(run(once=once))
