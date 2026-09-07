---
name: anti-ai-slop-design
description: "Aturan dan panduan desain UI tingkat tinggi untuk mencegah pola klise generik AI (AI slop), menghasilkan antarmuka editorial presisi, bernilai estetika tinggi, dan mematuhi Web Interface Guidelines."
---

# Anti-AI Slop Design & Editorial Interface Guidelines

Skill ini memandu AI agent dan desainer untuk menghasilkan antarmuka web yang **berkarakter, berkelas eksekutif, dan terbebas dari pola generik AI UI (AI Slop)**.

---

## 1. Anatomi "AI Slop" dalam UI (Dilarang Keras)

Hindari pola-pola klise yang membuat antarmuka terlihat seperti template generik buatan AI:

1. ❌ **Ikon & Badge Sparkles Berlebihan**: Menyematkan ikon `Sparkles` di setiap judul, badge, atau kartu seolah-olah semua hal adalah "keajaiban AI". Gantilah dengan label fungsional yang tenang dan percaya diri.
2. ❌ **Avatar Bot Raksasa Melayang**: Lingkaran avatar bot besar di tengah layar kosong dengan teks generik "Halo! Saya asisten AI, tanyakan apa saja...". Ganti dengan *Executive Command Deck* yang fungsional, bernilai guna langsung, dan menampilkan metrik siap pakai.
3. ❌ **Gelembung Chat Membulat Kebablasan (Pill Bubbles)**: Gelembung chat `rounded-3xl` warna ungu/biru neon khas chatbot mainan. Gunakan layout editorial terstruktur dengan garis arsitektural (*hairline*), tipografi tajam, dan struktur berbasis dokumen resmi.
4. ❌ **Sup Badge Warna-Warni Tanpa Hirarki**: Puluhan pill badge (hijau, biru, kuning, abu-abu) menumpuk tanpa kontras yang jelas.
5. ❌ **Palet SaaS Biru/Ungu Generik**: Jangan gunakan gradien biru-ke-ungu khas landing page AI template. Pertahankan identitas warna terkurasi (Copper/Terracotta `#cc785c`, Deep Charcoal Ink `#141413`, dan Warm Canvas `#faf9f5`).
6. ❌ **Tabel & Kontrol Kaku**: Tabel tanpa tipografi angka monospaced/tabular-nums, tanpa sticky header, dan input tanpa micro-interactions yang taktil.

---

## 2. Prinsip Desain Anti-Slop (Editorial Precision)

### A. Tipografi Bernyawa (Editorial Hierarchy)
- **Judul & Header Eksekutif**: Gunakan font serif editorial (`font-serif` / *Cormorant Garamond*) dengan proporsi anggun, *tracking* proporsional, dan *line-height* yang lega.
- **Data Finansial & Metrik**: WAJIB menggunakan `tabular-nums font-mono` agar angka-angka rupiah dan persentase tersusun sejajar rapi secara vertikal seperti laporan keuangan akuntan profesional.
- **Kerapian Teks**: Gunakan `text-pretty` atau `text-wrap: balance` pada judul untuk menghindari kata yatim (*widow words*).

### B. Arsitektur Ruang & Kartu (Warm Architectural Canvas)
- Gunakan warna kanvas hangat (`bg-canvas` / `#faf9f5`) dengan kartu putih bersih (`bg-white`), dibingkai garis batas halus (`border border-hairline` / `#e6dfd8`).
- Shadow harus sangat subtil dan realistis (`shadow-xs` atau `shadow-[0_1px_3px_rgba(0,0,0,0.04)]`), BUKAN bayangan tebal melayang yang kabur.
- Berikan ruang bernapas (*whitespace*) yang terukur sebagai elemen desain aktif, bukan ruang kosong tak bertuan.

### C. Antarmuka Chat & Hasil Data yang Berwibawa
- Pesan pengguna tampil ringkas, bersih, dan menyatu dengan kanvas tanpa warna yang mencolok mata.
- Jawaban AI diperlakukan layaknya **Laporan Eksekutif Lembar Kerja (Intelligence Dossier)**:
  - Header laporan yang jelas dengan status verifikasi yang elegan dan terintegrasi.
  - Tab data interaktif yang modern, tegas, dan intuitif.
  - Tabel dengan pemisah baris halus, header berarsitektur jelas, dan hover state yang lembut.
  - Toolbar aksi (Salin, Unduh Excel, Explain) seragam dalam bahasa visual konsisten.

### D. Standar Web Interface Guidelines (Vercel Labs)
- Tombol hanya-ikon WAJIB memiliki atribut `aria-label` dan `title`.
- Kontrol interaktif harus memiliki fokus yang jelas (`focus-visible:ring-1 focus-visible:ring-primary/40 focus:outline-none`).
- Animasi transisi harus berorientasi pada `transform` dan `opacity` yang halus (150ms–200ms), tanpa `transition: all`.
- Wadah teks fleksibel wajib memiliki `min-w-0` untuk mencegah kebocoran tata letak (*layout overflow*).
