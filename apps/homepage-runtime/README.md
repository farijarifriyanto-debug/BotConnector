# BotConnector Business Workflow v0.15.0

Tahap ini menghubungkan WhatsApp AI Admin Simulator dengan Business Operations.

## Fitur

- Sinkronisasi pesan simulasi ke database pelanggan dan prospek.
- Deduplikasi pelanggan berdasarkan kontak, lalu nama bila kontak kosong.
- Satu prospek aktif diperbarui oleh pesan berulang dari pelanggan yang sama.
- Draft WhatsApp masuk ke approval queue.
- Approval level 1: admin.
- Approval level 2: admin lalu manager/owner.
- Semua hasil akhir tetap `approved_not_sent`.
- Template balasan tersimpan.
- Aturan SLA per prioritas.
- Dashboard tugas admin.
- Ekspor CSV pelanggan, prospek, approval, booking, dan follow-up.
- Audit log dan versioning melalui Core API.

## Batas keamanan

- Tidak ada koneksi WhatsApp nyata.
- Tidak ada pesan yang dikirim.
- Tidak ada booking otomatis.
- Tidak ada scheduler follow-up.
- Tidak ada pembayaran.
- Tidak ada perubahan schema database.
- AI service tetap v0.4.0 dan tidak diubah.
