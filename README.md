# botconnector-poc — sandbox pembuktian 1·2·3·4

Repo terpisah untuk mencoba desain sebelum menyentuh repo produk/GitHub.
Tanpa dependensi (Node built-in saja). Tanpa push ke mana pun sampai disetujui.

## Yang dibuktikan (semua dengan cek nyata, bukan fake)

1. **Profile routing** (`lib/slots.mjs`) — daftar endpoint localhost, `ps` cek
   `/health` asli per profil, `switch` DITOLAK kalau target DOWN.
   Terbukti: stub 200 → switch OK; port mati → `ECONNREFUSED`, exit 1.
2. **Hardware fit** (`lib/hardware.mjs`) — deteksi nvidia-smi + rocm-smi +
   sysfs Intel + `system_profiler` Apple + override `POC_RAM_GB/POC_VRAM_GB/
   POC_CPU_CORES`. Skor great/ok/warn/no + confidence jujur
   (`estimated`/`override`/`n/a`). Terbukti: box ini → Intel iGPU shared,
   vramMax 0.
3. **Katalog MCP** (`data/mcp-catalog.json`, `lib/mcp.mjs`) — 5 server kurasi
   berlisensi (serena bertanda GPL-3.0: proses luar saja). Probe hanya cek
   binary launcher di PATH. Terbukti: docker/npx/uvx `+`, tool tak ada `x`.
4. **Launcher + TUI** (`lib/launcher.mjs`, `poc tui`) — deteksi 5 coding tool
   di PATH + preview config localhost. `--apply` SENGAJA tidak ada.
   Terbukti: opencode/claude/codex `+`, gemini `x`.

## Jalankan

```bash
npm run check && npm test   # 15/15
node bin/poc.mjs hw
node bin/poc.mjs mcp
node bin/poc.mjs launch
node bin/poc.mjs profiles add <nama> --url http://127.0.0.1:PORT
node bin/poc.mjs switch <nama>
node bin/poc.mjs tui        # TUI fullscreen ala opencode (butuh terminal TTY)
```

`poc tui`: alternate screen, slash menu (`/hw /ps /switch /add /rm /mcp /
launch /help /quit`), Tab melengkapi, Up/Down riwayat + navigasi menu,
Esc keluar, Ctrl+C paksa keluar. Di luar TTY otomatis fallback loop
sederhana. Semua perintah mengeksekusi fungsi lib yang sama dengan CLI.

## Yang TIDAK dibuktikan di sini

- Spawn/manage proses `llama-server` (itu milik repo produk, sudah ada di no 1 opsi A).
- Download model, billing cloud, installer, SSE/HTTP MCP transport.
