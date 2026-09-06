# BOTCONNECTOR_VISUAL_COMPOSER_V4_FIXED_MODULE
from __future__ import annotations

import html
from typing import Any


PROFILE = "hybrid-svg-idea-aware-v2-distinct-choices"


def _clean(
    value: object,
    maximum: int = 500,
) -> str:
    return " ".join(
        str(value or "").split()
    ).strip()[:maximum]


def _escape(
    value: object,
) -> str:
    return html.escape(
        str(value),
        quote=False,
    )


def _wrap(
    value: str,
    width: int,
    maximum_lines: int,
) -> list[str]:
    words = _clean(
        value,
        800,
    ).split()

    if not words:
        return []

    lines: list[str] = []
    current = ""

    for word in words:
        candidate = (
            word
            if not current
            else current + " " + word
        )

        if len(candidate) <= width:
            current = candidate
            continue

        if current:
            lines.append(current)

        current = word

        if len(lines) >= maximum_lines:
            break

    if current and len(lines) < maximum_lines:
        lines.append(current)

    consumed = sum(
        len(line.split())
        for line in lines
    )

    if consumed < len(words) and lines:
        last = lines[-1].rstrip(" .")
        lines[-1] = (
            last[: max(1, width - 1)]
            + "..."
        )

    return lines[:maximum_lines]


def _text(
    lines: list[str],
    *,
    x: int,
    y: int,
    size: int,
    weight: int = 400,
    fill: str = "#111827",
    line_height: int | None = None,
    anchor: str = "start",
    letter_spacing: int = 0,
) -> str:
    if not lines:
        return ""

    line_height = line_height or int(
        size * 1.22
    )

    spans: list[str] = []

    for index, line in enumerate(lines):
        dy = 0 if index == 0 else line_height

        spans.append(
            f'<tspan x="{x}" dy="{dy}">'
            f'{_escape(line)}'
            "</tspan>"
        )

    return (
        f'<text x="{x}" y="{y}" '
        'font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{size}" '
        f'font-weight="{weight}" '
        f'letter-spacing="{letter_spacing}" '
        f'fill="{fill}" '
        f'text-anchor="{anchor}">'
        + "".join(spans)
        + "</text>"
    )


def _context(
    payload: Any,
) -> tuple[str, str]:
    visuals = " ".join(
        _clean(item, 600)
        for item in getattr(
            payload,
            "visuals",
            [],
        )
    ).casefold()

    complete = " ".join(
        [
            _clean(
                getattr(payload, "title", ""),
                300,
            ),
            _clean(
                getattr(payload, "hook", ""),
                900,
            ),
            visuals,
            _clean(
                getattr(payload, "platform", ""),
                100,
            ),
            _clean(
                getattr(payload, "audience", ""),
                500,
            ),
        ]
    ).casefold()

    return visuals, complete


def _has(
    text: str,
    terms: tuple[str, ...],
) -> bool:
    return any(
        term in text
        for term in terms
    )


def category_key(
    payload: Any,
) -> str:
    _, context = _context(payload)

    if _has(
        context,
        (
            "instagram",
            "whatsapp",
            "kontak",
            "contact",
            "prospek",
            "lead",
            "pelanggan",
            "customer",
            "akun",
            "follower",
            "audiens",
        ),
    ):
        return "prospect"

    if _has(
        context,
        (
            "konten",
            "content",
            "creator",
            "kreator",
            "caption",
            "reels",
            "youtube",
            "tiktok",
            "video",
            "podcast",
        ),
    ):
        return "content"

    if _has(
        context,
        (
            "lowongan",
            "loker",
            "pekerjaan",
            "job",
            "karier",
            "career",
            "freelancer",
            "proposal",
            "lamaran",
            "resume",
        ),
    ):
        return "career"

    if _has(
        context,
        (
            "belajar",
            "study",
            "edukasi",
            "education",
            "siswa",
            "mahasiswa",
            "kursus",
            "tutorial",
            "pelajaran",
        ),
    ):
        return "study"

    if _has(
        context,
        (
            "keuangan",
            "finance",
            "profit",
            "investasi",
            "trading",
            "penjualan",
            "sales",
            "omzet",
            "pendapatan",
        ),
    ):
        return "finance"

    if _has(
        context,
        (
            "produk",
            "product",
            "toko",
            "jualan",
            "ecommerce",
            "e-commerce",
            "marketplace",
            "umkm",
            "usaha",
        ),
    ):
        return "commerce"

    return "general"


def template_key(
    payload: Any,
) -> str:
    visual_context, _ = _context(payload)

    # BOTCONNECTOR_EXPLICIT_TEMPLATE_MARKERS_V1
    # Pilihan dari kartu visual mempunyai prioritas
    # dibanding klasifikasi berbasis kata kunci.
    explicit_templates = (
        (
            "[botconnector_template:benefit]",
            "benefit",
        ),
        (
            "[botconnector_template:process]",
            "process",
        ),
        (
            "[botconnector_template:before_after]",
            "before_after",
        ),
    )

    for template_marker, template_name in (
        explicit_templates
    ):
        if template_marker in visual_context:
            return template_name

    if _has(
        visual_context,
        (
            "sebelum dan sesudah",
            "sebelum-sesudah",
            "before after",
            "before-after",
            "perbandingan",
            "masalah dan solusi",
            "problem solution",
            "kiri dan kanan",
        ),
    ):
        return "before_after"

    if _has(
        visual_context,
        (
            "cara kerja",
            "langkah",
            "tahap",
            "alur",
            "proses",
            "step",
            "workflow",
            "urutan",
        ),
    ):
        return "process"

    if _has(
        visual_context,
        (
            "manfaat",
            "hasil utama",
            "keuntungan",
            "benefit",
            "lebih cepat",
            "lebih mudah",
            "hasil akhir",
            "promosi",
            "cover",
        ),
    ):
        return "benefit"

    category = category_key(payload)

    if category in {
        "prospect",
        "content",
        "career",
        "study",
    }:
        return "process"

    return "benefit"


CONFIGS: dict[str, dict[str, object]] = {
    "prospect": {
        "eyebrow": "OTOMATISASI PROSPEK",
        "subtitle": (
            "Temukan calon pelanggan "
            "lebih cepat dan terarah."
        ),
        "steps": [
            (
                "Temukan akun",
                "Kumpulkan profil yang relevan.",
            ),
            (
                "Saring prospek",
                "Pilih calon pelanggan potensial.",
            ),
            (
                "Susun kontak",
                "Rapikan agar mudah ditindaklanjuti.",
            ),
        ],
        "benefits": [
            "Lebih cepat",
            "Lebih terarah",
            "Lebih rapi",
        ],
        "before": [
            "Pencarian manual",
            "Kontak tersebar",
            "Sulit ditindaklanjuti",
        ],
        "after": [
            "Prospek tersaring",
            "Kontak tersusun",
            "Siap ditindaklanjuti",
        ],
        "cta": "Cari - Saring - Susun",
    },
    "content": {
        "eyebrow": "CREATOR ASSISTANT",
        "subtitle": (
            "Ubah satu ide menjadi konten "
            "yang siap digunakan."
        ),
        "steps": [
            (
                "Temukan ide",
                "Pilih sudut yang paling relevan.",
            ),
            (
                "Susun pesan",
                "Buat hook dan alur yang jelas.",
            ),
            (
                "Siapkan konten",
                "Lengkapi caption dan ajakan.",
            ),
        ],
        "benefits": [
            "Ide lebih jelas",
            "Proses lebih cepat",
            "Konten lebih rapi",
        ],
        "before": [
            "Bingung memulai",
            "Pesan tidak fokus",
            "Konten tertunda",
        ],
        "after": [
            "Ide terarah",
            "Pesan lebih kuat",
            "Siap dipublikasikan",
        ],
        "cta": "Ide - Susun - Terbitkan",
    },
    "career": {
        "eyebrow": "WORK AND CAREER",
        "subtitle": (
            "Kelola peluang kerja dan "
            "langkah lamaran dengan rapi."
        ),
        "steps": [
            (
                "Temukan peluang",
                "Pilih pekerjaan yang relevan.",
            ),
            (
                "Siapkan lamaran",
                "Susun dokumen dan proposal.",
            ),
            (
                "Pantau proses",
                "Catat status dan tindak lanjut.",
            ),
        ],
        "benefits": [
            "Peluang relevan",
            "Dokumen rapi",
            "Status terpantau",
        ],
        "before": [
            "Pencarian acak",
            "Dokumen tercecer",
            "Status terlupa",
        ],
        "after": [
            "Peluang terpilih",
            "Lamaran siap",
            "Proses terpantau",
        ],
        "cta": "Cari - Siapkan - Pantau",
    },
    "study": {
        "eyebrow": "STUDY ASSISTANT",
        "subtitle": (
            "Pelajari materi dengan alur "
            "yang lebih sederhana."
        ),
        "steps": [
            (
                "Pahami materi",
                "Temukan inti pembahasan.",
            ),
            (
                "Susun ringkasan",
                "Rapikan poin penting.",
            ),
            (
                "Uji pemahaman",
                "Gunakan latihan dan evaluasi.",
            ),
        ],
        "benefits": [
            "Lebih terarah",
            "Mudah dipahami",
            "Siap diuji",
        ],
        "before": [
            "Materi menumpuk",
            "Poin tidak jelas",
            "Sulit mengingat",
        ],
        "after": [
            "Materi terstruktur",
            "Inti lebih jelas",
            "Belajar lebih fokus",
        ],
        "cta": "Pahami - Ringkas - Latih",
    },
    "finance": {
        "eyebrow": "BUSINESS INSIGHT",
        "subtitle": (
            "Lihat proses dan hasil bisnis "
            "dengan lebih jelas."
        ),
        "steps": [
            (
                "Kumpulkan data",
                "Satukan informasi penting.",
            ),
            (
                "Baca kondisi",
                "Temukan pola dan prioritas.",
            ),
            (
                "Ambil tindakan",
                "Jalankan keputusan terukur.",
            ),
        ],
        "benefits": [
            "Data lebih jelas",
            "Keputusan cepat",
            "Hasil terukur",
        ],
        "before": [
            "Data tersebar",
            "Analisis lambat",
            "Keputusan tertunda",
        ],
        "after": [
            "Data tersusun",
            "Kondisi terbaca",
            "Tindakan terarah",
        ],
        "cta": "Data - Analisis - Tindakan",
    },
    "commerce": {
        "eyebrow": "SMART BUSINESS",
        "subtitle": (
            "Rapikan proses penjualan "
            "dan pelayanan pelanggan."
        ),
        "steps": [
            (
                "Tampilkan produk",
                "Susun penawaran yang jelas.",
            ),
            (
                "Layani pelanggan",
                "Jawab kebutuhan lebih cepat.",
            ),
            (
                "Kelola pesanan",
                "Pantau proses hingga selesai.",
            ),
        ],
        "benefits": [
            "Penawaran jelas",
            "Respons cepat",
            "Pesanan rapi",
        ],
        "before": [
            "Informasi tersebar",
            "Respons terlambat",
            "Pesanan sulit dilacak",
        ],
        "after": [
            "Produk terstruktur",
            "Pelanggan terlayani",
            "Pesanan terpantau",
        ],
        "cta": "Tawarkan - Layani - Kelola",
    },
    "general": {
        "eyebrow": "BOTCONNECTOR AUTOMATION",
        "subtitle": (
            "Sederhanakan pekerjaan menjadi "
            "alur yang mudah dipahami."
        ),
        "steps": [
            (
                "Masukkan kebutuhan",
                "Jelaskan tujuan dengan bahasa biasa.",
            ),
            (
                "Susun proses",
                "Ubah kebutuhan menjadi langkah jelas.",
            ),
            (
                "Gunakan hasil",
                "Tinjau dan jalankan saat siap.",
            ),
        ],
        "benefits": [
            "Lebih sederhana",
            "Lebih cepat",
            "Lebih terarah",
        ],
        "before": [
            "Proses manual",
            "Informasi tersebar",
            "Pekerjaan tertunda",
        ],
        "after": [
            "Alur tersusun",
            "Informasi jelas",
            "Siap digunakan",
        ],
        "cta": "Jelaskan - Susun - Gunakan",
    },
}


def _config(
    category: str,
) -> dict[str, object]:
    return CONFIGS.get(
        category,
        CONFIGS["general"],
    )


def _process(
    config: dict[str, object],
) -> str:
    steps = list(config["steps"])
    y_values = [485, 690, 895]

    parts = [
        '<g id="template-process">',
        (
            '<path d="M153 555 L153 965" '
            'stroke="#D9D5FF" stroke-width="14" '
            'stroke-linecap="round"/>'
        ),
    ]

    for index, step in enumerate(steps[:3]):
        heading, description = step
        y = y_values[index]

        parts.extend(
            [
                (
                    f'<circle cx="153" cy="{y + 70}" '
                    'r="48" fill="#5B4CF0"/>'
                ),
                _text(
                    [str(index + 1)],
                    x=153,
                    y=y + 84,
                    size=38,
                    weight=700,
                    fill="#FFFFFF",
                    anchor="middle",
                ),
                (
                    f'<rect x="220" y="{y}" '
                    'width="760" height="145" rx="34" '
                    'fill="#FFFFFF" filter="url(#shadow)"/>'
                ),
                (
                    f'<circle cx="282" cy="{y + 72}" '
                    'r="30" fill="#EEEAFE"/>'
                ),
                (
                    f'<path d="M267 {y + 72} '
                    f'L277 {y + 82} L299 {y + 58}" '
                    'fill="none" stroke="#5B4CF0" '
                    'stroke-width="8" '
                    'stroke-linecap="round" '
                    'stroke-linejoin="round"/>'
                ),
                _text(
                    [_clean(heading, 80)],
                    x=340,
                    y=y + 62,
                    size=35,
                    weight=700,
                ),
                _text(
                    _wrap(
                        _clean(description, 160),
                        43,
                        2,
                    ),
                    x=340,
                    y=y + 104,
                    size=24,
                    fill="#667085",
                    line_height=30,
                ),
            ]
        )

    parts.append("</g>")
    return "".join(parts)


def _benefit(
    config: dict[str, object],
) -> str:
    benefits = list(config["benefits"])
    x_values = [92, 373, 654]

    parts = [
        '<g id="template-benefit">',
        (
            '<circle cx="540" cy="665" r="180" '
            'fill="#EEEAFE"/>'
        ),
        (
            '<circle cx="540" cy="610" r="66" '
            'fill="#FFD8BF"/>'
        ),
        (
            '<path d="M421 820 C438 710 642 710 659 820 '
            'L659 865 L421 865 Z" fill="#5B4CF0"/>'
        ),
        (
            '<circle cx="365" cy="590" r="30" '
            'fill="#34C38F"/>'
        ),
        (
            '<circle cx="728" cy="575" r="38" '
            'fill="#FFB84D"/>'
        ),
        (
            '<circle cx="350" cy="755" r="42" '
            'fill="#A69BFF"/>'
        ),
        (
            '<path d="M388 603 C430 620 460 620 485 615" '
            'fill="none" stroke="#5B4CF0" '
            'stroke-width="8" stroke-linecap="round"/>'
        ),
        (
            '<path d="M594 613 C645 605 682 592 694 584" '
            'fill="none" stroke="#5B4CF0" '
            'stroke-width="8" stroke-linecap="round"/>'
        ),
        (
            '<path d="M388 739 C433 710 457 692 485 661" '
            'fill="none" stroke="#5B4CF0" '
            'stroke-width="8" stroke-linecap="round"/>'
        ),
    ]

    for index, benefit in enumerate(
        benefits[:3]
    ):
        x = x_values[index]

        parts.extend(
            [
                (
                    f'<rect x="{x}" y="920" '
                    'width="254" height="150" rx="32" '
                    'fill="#FFFFFF" filter="url(#shadow)"/>'
                ),
                (
                    f'<circle cx="{x + 40}" cy="963" '
                    'r="17" fill="#34C38F"/>'
                ),
                (
                    f'<path d="M{x + 31} 963 '
                    f'L{x + 38} 970 L{x + 51} 952" '
                    'fill="none" stroke="#FFFFFF" '
                    'stroke-width="5" '
                    'stroke-linecap="round" '
                    'stroke-linejoin="round"/>'
                ),
                _text(
                    _wrap(
                        _clean(benefit, 80),
                        15,
                        2,
                    ),
                    x=x + 28,
                    y=1020,
                    size=29,
                    weight=700,
                    line_height=34,
                ),
            ]
        )

    parts.append("</g>")
    return "".join(parts)


def _before_after(
    config: dict[str, object],
) -> str:
    before = list(config["before"])
    after = list(config["after"])

    parts = [
        '<g id="template-before-after">',
        (
            '<rect x="72" y="470" width="438" '
            'height="610" rx="42" fill="#FFF3EC" '
            'filter="url(#shadow)"/>'
        ),
        (
            '<rect x="570" y="470" width="438" '
            'height="610" rx="42" fill="#EEFBF6" '
            'filter="url(#shadow)"/>'
        ),
        _text(
            ["SEBELUM"],
            x=112,
            y=540,
            size=27,
            weight=700,
            fill="#D76D35",
            letter_spacing=2,
        ),
        _text(
            ["SESUDAH"],
            x=610,
            y=540,
            size=27,
            weight=700,
            fill="#19865F",
            letter_spacing=2,
        ),
        (
            '<circle cx="291" cy="675" r="92" '
            'fill="#FFD7C4"/>'
        ),
        (
            '<path d="M245 646 L337 704 M337 646 L245 704" '
            'stroke="#D76D35" stroke-width="15" '
            'stroke-linecap="round"/>'
        ),
        (
            '<circle cx="789" cy="675" r="92" '
            'fill="#C7F1DF"/>'
        ),
        (
            '<path d="M744 675 L775 706 L838 637" '
            'fill="none" stroke="#19865F" '
            'stroke-width="17" '
            'stroke-linecap="round" '
            'stroke-linejoin="round"/>'
        ),
    ]

    for index, value in enumerate(
        before[:3]
    ):
        y = 835 + index * 65

        parts.extend(
            [
                (
                    f'<circle cx="121" cy="{y - 8}" '
                    'r="9" fill="#D76D35"/>'
                ),
                _text(
                    _wrap(
                        _clean(value, 100),
                        24,
                        2,
                    ),
                    x=148,
                    y=y,
                    size=25,
                    weight=600,
                    fill="#783B25",
                    line_height=29,
                ),
            ]
        )

    for index, value in enumerate(
        after[:3]
    ):
        y = 835 + index * 65

        parts.extend(
            [
                (
                    f'<circle cx="619" cy="{y - 8}" '
                    'r="9" fill="#19865F"/>'
                ),
                _text(
                    _wrap(
                        _clean(value, 100),
                        24,
                        2,
                    ),
                    x=646,
                    y=y,
                    size=25,
                    weight=600,
                    fill="#155C45",
                    line_height=29,
                ),
            ]
        )

    parts.append("</g>")
    return "".join(parts)


def compose_svg(
    payload: Any,
) -> str:
    category = category_key(payload)
    template = template_key(payload)
    config = _config(category)

    title = _clean(
        getattr(payload, "title", ""),
        240,
    )

    if (
        not title
        or title.casefold().startswith(
            "ide konten "
        )
    ):
        title = str(config["subtitle"])

    title_lines = _wrap(
        title,
        width=27,
        maximum_lines=3,
    )

    subtitle_lines = _wrap(
        str(config["subtitle"]),
        width=52,
        maximum_lines=2,
    )

    if template == "before_after":
        body = _before_after(config)
    elif template == "benefit":
        body = _benefit(config)
    else:
        body = _process(config)

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg
  xmlns="http://www.w3.org/2000/svg"
  width="1080"
  height="1350"
  viewBox="0 0 1080 1350"
  role="img"
  aria-labelledby="visual-title visual-desc"
>
  <title id="visual-title">{_escape(title)}</title>
  <desc id="visual-desc">
    Visual BotConnector yang disusun berdasarkan ide konten.
  </desc>

  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#F8F7FF"/>
      <stop offset="55%" stop-color="#F4F7FC"/>
      <stop offset="100%" stop-color="#EEF9F5"/>
    </linearGradient>

    <linearGradient id="cta-gradient" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#5B4CF0"/>
      <stop offset="100%" stop-color="#7768F5"/>
    </linearGradient>

    <filter id="shadow" x="-20%" y="-20%" width="140%" height="160%">
      <feDropShadow
        dx="0"
        dy="16"
        stdDeviation="18"
        flood-color="#2F2A5A"
        flood-opacity="0.12"
      />
    </filter>
  </defs>

  <rect width="1080" height="1350" fill="url(#background)"/>

  <circle
    cx="1010"
    cy="100"
    r="190"
    fill="#E7E3FF"
    opacity="0.65"
  />

  <circle
    cx="70"
    cy="1280"
    r="180"
    fill="#DDF7EC"
    opacity="0.75"
  />

  <rect
    x="72"
    y="58"
    width="300"
    height="52"
    rx="26"
    fill="#EEEAFE"
  />

  {_text(
      [_clean(config["eyebrow"], 80)],
      x=222,
      y=92,
      size=21,
      weight=700,
      fill="#5B4CF0",
      anchor="middle",
      letter_spacing=2,
  )}

  {_text(
      title_lines,
      x=72,
      y=200,
      size=59,
      weight=800,
      fill="#111827",
      line_height=68,
  )}

  {_text(
      subtitle_lines,
      x=72,
      y=410,
      size=28,
      fill="#667085",
      line_height=36,
  )}

  {body}

  <rect
    x="72"
    y="1168"
    width="936"
    height="104"
    rx="34"
    fill="url(#cta-gradient)"
  />

  {_text(
      [_clean(config["cta"], 100)],
      x=112,
      y=1232,
      size=30,
      weight=700,
      fill="#FFFFFF",
  )}

  {_text(
      ["BOTCONNECTOR"],
      x=956,
      y=1227,
      size=19,
      weight=700,
      fill="#FFFFFF",
      anchor="end",
      letter_spacing=2,
  )}

  {_text(
      ["Visual disusun sesuai ide konten"],
      x=956,
      y=1254,
      size=16,
      fill="#E8E6FF",
      anchor="end",
  )}

  <text
    x="72"
    y="1320"
    font-family="Arial, Helvetica, sans-serif"
    font-size="17"
    fill="#8A94A6"
  >
    Template: {_escape(template.replace("_", " ").title())}
    - Format Instagram 4:5
  </text>
</svg>
'''
