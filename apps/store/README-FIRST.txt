BOTCONNECTOR STORE — PRODUCTION V6R2 FINAL
========================================
Tanggal release: 12 Agustus 2026
Public URL: https://botconnector.id/store/
Service: botconnector-store.service
Listen: 127.0.0.1:18194

V6R2 HOTFIX
- Memperbaiki pemilihan server block Nginx: deployment hanya boleh memasang /store/ pada HTTPS apex
  `server_name botconnector.id;`, bukan blok redirect `www.botconnector.id`.
- Memperbaiki pengecekan rute APK agar menggunakan GET, sesuai route download FastAPI.

TUJUAN RELEASE
- Store publik mengikuti desain V6 yang sudah disepakati: light-first, langsung ke daftar produk,
  tanpa label “BotConnector Business”, tanpa slogan/hero panjang, dan tanpa bahasa teknis internal.
- Empat produk ditampilkan dengan nama yang mudah dipahami pembeli:
  Restoran & Kafe, Cuci Kendaraan, Bengkel, Toko & Retail.
- Nama APK/produk internal tetap dipertahankan hanya untuk integrasi lisensi dan download.

HARGA DEFAULT STORE
Restoran & Kafe
  Dasar        Rp179.000
  Lengkap      Rp299.000
  Profesional  Rp499.000
  Multi Lokasi Rp799.000

Cuci Kendaraan
  Dasar        Rp99.000
  Lengkap      Rp179.000

Bengkel
  Dasar        Rp149.000
  Lengkap      Rp249.000
  Profesional  Rp399.000

Toko & Retail
  Dasar        Rp129.000
  Lengkap      Rp229.000
  Profesional  Rp349.000

Catatan paket:
- Store hanya menampilkan paket yang saat ini membuka perbedaan fitur nyata pada APK.
- Edition internal yang belum punya gating fitur unik tetap ada di Universal License Engine,
  tetapi tidak dijual pada Store sampai fiturnya benar-benar tersedia.
- Harga dapat diubah dari /store/admin/ tanpa rebuild APK atau Store.
- Peningkatan paket dihitung dari harga paket aktif yang dibaca dari Seller Control,
  bukan dari pilihan paket lama yang dikirim browser.

FITUR PRODUCTION
- Store utama + 4 halaman produk.
- Responsive desktop/mobile.
- Trial 3 hari, sekali per aplikasi/perangkat.
- Pembelian Lisensi Penuh.
- Peningkatan paket pada APK yang sama.
- Status pesanan dan kode aktivasi.
- APK universal resmi dengan SHA-256 yang diverifikasi saat deploy.
- Store Admin: daftar pesanan, konfirmasi pembayaran manual, penerbitan ulang bila perlu,
  pembatalan pesanan pending, dan editor harga.
- Midtrans Snap production/sandbox.
- Webhook Midtrans dengan signature SHA-512, verifikasi nominal, status/fraud checks,
  idempotent fulfillment, dan X-Override-Notification per transaksi.
- Upgrade tidak mempercayai paket asal dari browser; paket aktif dibaca langsung dari Seller Control.
- Pencegahan pesanan aktif ganda untuk aplikasi/perangkat yang sama.
- Halaman pesanan dilindungi cookie capability HttpOnly/Secure, bukan token di URL.
- Admin cookie HttpOnly/Secure/SameSite=Strict + rate limit login.
- CSP, X-Frame-Options, no-referrer, nosniff, no-store untuk halaman sensitif.
- FastAPI hanya listen di loopback dan hanya mempercayai forwarded header dari 127.0.0.1.
- Nginx reverse proxy /store/ dengan backup, nginx -t, dan rollback otomatis bila deploy gagal.
- Seller Control API internal hanya di 127.0.0.1:18192 dan dilindungi shared secret.
- Private signing key tetap di Seller Control; Store tidak menerima salinan private key.

APK RESMI DALAM PAKET
Vehicle-Wash-2.0.0-Universal-License.apk
Workshop-2.0.0-Universal-License.apk
Retail-2.0.0-Universal-License.apk
Restaurant-All-in-One-R8-Universal-License.apk

INSTALL
1. Upload ZIP ke /home/botadmin lalu ekstrak.
2. Masuk ke folder hasil ekstrak.
3. Verifikasi checksum:

   sha256sum -c SHA256SUMS.txt

4. Deploy:

   sudo bash deploy-store-v6.sh

Deploy melakukan backup Store DB/env, Seller Control, dan Nginx sebelum perubahan.
Jika validasi Nginx atau health check gagal, script akan mencoba memulihkan release/config sebelumnya.

URL SETELAH DEPLOY
https://botconnector.id/store/
https://botconnector.id/store/restaurant/
https://botconnector.id/store/vehicle-wash/
https://botconnector.id/store/workshop/
https://botconnector.id/store/retail/
https://botconnector.id/store/panduan/
https://botconnector.id/store/status/
https://botconnector.id/store/admin/

PEMBAYARAN
Default deploy menggunakan mode manual supaya Store tidak berpura-pura menerima pembayaran online
sebelum Server Key merchant tersedia.

Untuk mengaktifkan Midtrans:

   sudo bash configure-midtrans.sh production

Masukkan Midtrans Server Key saat diminta. Store akan membuat Snap transaction dari backend dan
mengirim X-Override-Notification ke:
https://botconnector.id/store/api/payment/midtrans

Tidak perlu menaruh Server Key di browser/JavaScript.

PRODUCTION CHECK
Setelah deploy:

   sudo bash production-check.sh

Script memeriksa service, health, Nginx, 4 halaman produk, 4 APK, Seller Control API auth,
dan endpoint publik utama.

ROLLBACK STORE

   sudo bash rollback-store-v6.sh

Rollback berpindah ke release Store sebelumnya. Database pesanan tidak dihapus dan Universal
License Engine/Seller Control tidak dihapus.

CATATAN RESTAURANT R8
Restaurant R8 menggunakan signing certificate production. R5/R6/R7 lama menggunakan certificate
uji yang berbeda. Migrasi dari R5/R6/R7 ke R8 membutuhkan uninstall satu kali setelah data penting
diamankan. Setelah R8, pertahankan signing certificate production yang sama untuk update berikutnya.

BATASAN YANG DISENGAJA
- Credential Midtrans tidak disertakan dalam ZIP.
- Store tidak mengubah private signing key.
- Store tidak mengklaim paket multi-lokasi pada APK yang belum mempunyai fitur native berbeda.

RECOVERY DARI DEPLOY V6 YANG BERHENTI DI HTTPS /store/ 404
Jika V6 lama sudah memasang service tetapi rollback Nginx karena /store/ 404, jalankan:

   sudo bash repair-store-v6r2.sh

Script ini hanya memperbaiki route Nginx Store, membuat backup, melakukan nginx -t, reload,
dan memverifikasi Store + empat APK menggunakan GET.
