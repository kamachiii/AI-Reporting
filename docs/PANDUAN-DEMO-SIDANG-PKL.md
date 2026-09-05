# Panduan Skenario Live Demo & Presentasi Sidang PKL
## DMS AI Platform: Multi-Tenant Automotive Analytics & Deterministic Text-to-SQL Engine

> **Dokumen Panduan Pengujian & Presentasi Eksekutif**  
> Disusun untuk keperluan demonstrasi langsung (*live demo*) di hadapan penguji sidang, pembimbing PKL, dan manajemen dealer otomotif.

---

## 1. Ringkasan Eksekutif & Masalah yang Diselesaikan

### Permasalahan Nyata di Industri Dealer Otomotif:
1. **Skema Database Raksasa & Sangat Kompleks**:
   - Database dealer (seperti Otobitz Cloud) memiliki **2.387+ tabel** dengan relasi rumit.
   - Model LLM murni (*pure text-to-sql*) langsung gagal karena batasan context window (*Token Per Minute limit*) dan tingginya risiko salah tafsir relasi tabel.
2. **Bahaya Halusinasi Angka**:
   - LLM generatif sering mengarang (*hallucinate*) nominal omzet, jumlah unit, atau piutang dealer. Dalam konteks laporan keuangan, kesalahan 1 digit berakibat fatal.
3. **Risiko Keamanan & Query Destruktif**:
   - Query SQL yang langsung dieksekusi tanpa filter dapat menyebabkan `DROP TABLE`, `DELETE`, `UPDATE`, kebocoran data gaji, atau *denial of service* (query gantung tanpa timeout).
4. **Biaya Token yang Sangat Mahal pada Solusi Kompetitor**:
   - Solusi kompetitor (seperti arsitektur ReAct Vanna pada Otobitz) membakar **~18.840 token per satu pertanyaan**, lambat (~10-20 detik), dan tidak memiliki mekanisme hemat biaya.

### Solusi Arsitektur Unggulan DMS AI Platform:
- **Dua Tier + 6-Gate AST Verifier**: Default-deny, hanya SQL lolos verifikasi sintaks dan skema yang boleh jalan di database read-only.
- **Presenter with Number Check**: Angka dalam narasi wajib lolos verifikasi mekanis terhadap data riil database; jika ada 1 angka tidak cocok, fallback otomatis ke template deterministik.
- **SQL Memory Replay**: Jawaban yang dikonfirmasi user diputar ulang pada pertanyaan berikutnya dengan **0 Token LLM** dan keyakinan Level A.
- **Auto-Adaptive Visual Charts & Executive Excel Export**: Grafik Recharts interaktif instan di browser dan unduhan file spreadsheet `.xlsx` berstandar akuntansi dengan chart native Excel.

---

## 2. Matriks Perbandingan Ilmiah: DMS AI vs Kompetitor (Vanna Otobitz)

| Dimensi Parameter | Solusi Kompetitor (Vanna / Otobitz ReAct) | DMS AI Platform (Sistem Kita) |
|---|---|---|
| **Konsumsi Token per Kueri** | **~18.840 token** (Loop reasoning berulang-ulang) | **0 s/d ~650 token** (*Hemat >95% biaya API*) |
| **Kecepatan Respons** | Lambat (12 – 25 detik) | **Cepat (< 1 – 3 detik)**, Memory Replay **< 200 ms** |
| **Garansi Presisi Angka** | Tidak ada (Bisa mengarang angka di ringkasan naratif) | **NUMBER CHECK Mekanis** (0 toleransi halusinasi) |
| **Keamanan Eksekusi Database** | Bergantung pada prompt system LLM | **6-Gate Verifier AST (Default-Deny)** + Timeout 10s + Read-Only Cap 500 |
| **Penyajian Visual** | Teks polos atau tabel kaku mentah | **Grafik Visual Interaktif 0-Token** (Bar/Line toggle) + Tooltip Rupiah |
| **Ekspor Laporan** | Hanya CSV mentah tanpa format | **Excel `.xlsx` Akuntansi** + **Native Embedded Chart** bawaan Excel |
| **Kueri Multidomain 3S** | Gagal atau butuh tanya 3 kali terpisah | **Query Fan-Out Otomatis** (Sales, Service, Sparepart dalam 1 pertanyaan) |
| **Pengawasan Manajemen** | Kotak hitam (tidak ada pemantauan token) | **Admin Dashboard Real-Time**: Kuota harian cabang & penghematan biaya |

---

## 3. Langkah-demi-Langkah Skenario Live Demo Sidang

Sebelum memulai presentasi, pastikan backend dan frontend aktif:
- **URL Frontend**: `http://localhost:5173`
- **Backend API**: `http://localhost:8000`

---

### Skenario 1: Pertanyaan Emas Penjualan Kuartal + Visual Grafik Garis/Batang
*Tujuan: Membuktikan pemahaman skema dealer otomotif dan visualisasi grafik instan tanpa token tambahan.*

1. Login sebagai user cabang:
   - **Username**: `tester01`
   - **Password**: `tester123`
   - Cabang aktif: **TST_01** (Terhubung ke database demo 2.387 tabel).
2. Ajukan pertanyaan di chat:
   > *"berikan rincian data penjualan per kuartal di tahun 2025 yang mencakup kuartal, jumlah unit terjual, total omzet penjualan, dan rata-rata harga jual unit"*
3. **Poin yang Ditunjukkan ke Penguji**:
   - Sistem langsung menjawab dengan data riil database.
   - Tampilan otomatis memilih mode **Grafik Visual** (karena mendeteksi dimensi waktu kuartal).
   - Tunjukkan interaktivitas grafik: hover mouse pada grafik untuk melihat tooltip Rupiah akurat.
   - Klik toggle **Grafik Garis Tren** dan **Grafik Batang** untuk melihat fleksibilitas analisis visual.
   - Buka tab **Tabel Data** untuk memperlihatkan format Rupiah akuntansi Indonesia.
   - Tunjukkan bagian bawah: **Transparansi SQL Parameterized** yang bersih dan aman.

---

### Skenario 2: Ekspor Excel Berformat Akuntansi & Grafik Native Bawaan
*Tujuan: Membuktikan laporan siap pakai level manajer/direksi dengan spreadsheet berstandar profesional.*

1. Pada kartu jawaban Skenario 1 di atas, klik tombol hijau **"Unduh Excel"** dengan ikon spreadsheet.
2. File terunduh secara instan (nama file dinamis sesuai pertanyaan dan cabang, misal: `Laporan_berikan_rincian_data_penjualan_TST_01.xlsx`).
3. Buka file `.xlsx` tersebut di Microsoft Excel di hadapan penguji:
   - **Poin yang Ditunjukkan**:
     - Header laporan eksekutif lengkap dengan judul, cabang, dan waktu cetak.
     - Styling tabel *Navy Blue* (`#1E3A8A`) dengan border rapi dan format sel Rupiah akuntansi resmi `Rp #,##0`.
     - **Grafik Asli (*Native Embedded Chart*)**: Grafik di dalam Excel bukan gambar hasil screenshot (*bitmap*), melainkan objek chart Excel asli yang terhubung langsung ke sel data (bisa diedit tipenya di Excel).

---

### Skenario 3: Kueri Proaktif Multi-Table 3S Fan-Out (Sales, Service, Sparepart)
*Tujuan: Membuktikan keunggulan analitik holistik dealer 3S yang tidak bisa dilakukan sistem biasa.*

1. Ajukan pertanyaan evaluasi transaksi dealer:
   > *"bagaimana performa transaksi tahun 2025"*
2. **Poin yang Ditunjukkan ke Penguji**:
   - Sistem secara proaktif menyadari bahwa operasional dealer 3S mencakup 3 pilar: Penjualan Mobil (*Unit*), Bengkel Servis (*GR/BP*), dan Penjualan Suku Cadang (*Sparepart*).
   - Sistem menjalankan **Query Fan-Out Paralel** menggunakan `asyncio.gather`.
   - Di antarmuka chat muncul **Switcher Tab Dinamis 3S**:
     - Tab 1: *Unit Kendaraan* (menampilkan penjualan unit mobil).
     - Tab 2: *Jasa Servis Bengkel* (menampilkan unit entry dan jasa mekanik).
     - Tab 3: *Suku Cadang & Sparepart* (menampilkan perputaran barang gudang).
   - Masing-masing tab memiliki tabel dan visualisasi grafiknya sendiri.

---

### Skenario 4: Interactive Clarification Loop (Human-in-the-Loop 0-Token)
*Tujuan: Membuktikan penanganan ambiguitas istilah otomotif secara instan tanpa halusinasi.*

1. Ajukan pertanyaan yang ambigu:
   > *"tampilkan data oli"*
2. **Poin yang Ditunjukkan ke Penguji**:
   - Sistem **tidak mengarang jawaban** dan **tidak membuang token LLM**.
   - Dalam hitungan <10 ms, muncul **ClarificationCard**:
     - *Pilihan A*: Unit Kendaraan (Oli bawaan unit / delivery inspection).
     - *Pilihan B*: Suku Cadang & Bengkel (Oli pelumas servis berkala / gudang part).
   - Klik salah satu tombol pilihan, dan kueri langsung dilanjutkan dengan konteks yang tepat.

---

### Skenario 5: Pembuktian SQL Memory Replay (0 Token & Keyakinan Level A)
*Tujuan: Memperlihatkan efisiensi operasional dan penghematan biaya total.*

1. Pada jawaban yang sudah diverifikasi benar, klik tombol **"Jawaban benar"** (Thumbs Up).
2. Sistem mencatatnya ke `sql_memory` dengan status *APPROVED*.
3. Buka sesi chat baru atau ketik pertanyaan yang sama persis:
   > *"berikan rincian data penjualan per kuartal di tahun 2025 yang mencakup kuartal, jumlah unit terjual, total omzet penjualan, dan rata-rata harga jual unit"*
4. **Poin yang Ditunjukkan ke Penguji**:
   - Badge keyakinan menampilkan: **Keyakinan Level A (SQL Memory Replay)**.
   - **0 Panggilan API ke LLM** dan durasi respon <200 ms.
   - Membuktikan bahwa pertanyaan rutin harian dealer tidak membebani biaya API sama sekali.

---

### Skenario 6: Uji Ketahanan Keamanan 6-Gate Verifier (SQL Injection & Destruktif)
*Tujuan: Membuktikan bahwa sistem enterprise-grade dan tidak bisa disalahgunakan.*

1. Coba lakukan serangan SQL Injection atau perintah berbahaya:
   > *"hapus tabel penjualan unit"* atau *"SELECT * FROM users; DROP TABLE branches;"*
2. **Poin yang Ditunjukkan ke Penguji**:
   - Sistem **menolak mentah-mentah** permintaan tersebut sebelum menyentuh database tenant.
   - Muncul pesan penolakan yang ramah namun tegas dari Verifier Gerbang #1 AST Parser.
   - Database tetap 100% aman dan utuh.
   - Percobaan serangan tercatat otomatis di Audit Log dengan status **`rejected`**.

---

### Skenario 7: Showcase Panel Admin (Pemantauan Kuota & Metrik Utilisasi AI)
*Tujuan: Memperlihatkan kontrol penuh tim IT/Manajemen terhadap anggaran dan performa AI.*

1. Logout dari user, lalu login sebagai Administrator:
   - **Username**: `admin`
   - **Password**: `admin123`
2. Buka menu **Audit Log & Analitik AI** (`/admin/audit-log`):
3. **Poin yang Ditunjukkan ke Penguji**:
   - **4 Kartu Metrik Eksekutif**:
     - Total kueri AI & Success Rate kueri.
     - **Estimasi Penghematan Token dari SQL Memory**: Memperlihatkan angka konkret token dan estimasi biaya yang dihemat.
     - Estimasi Token Terpakai Hari Ini.
     - Rata-rata latensi eksekusi database.
   - **Grafik Tren 7 Hari**: Area chart interaktif membandingkan kueri LLM baru vs Memory Replay 0-Token.
   - **Tabel Pemantauan Kuota Cabang**:
     - Menampilkan cabang `TST_01`, `JKT_01`, status utilisasi harian, dan bar kuota warna-warni (Hijau / Amber / Merah).
   - **Fitur Ubah Kuota Real-Time**:
     - Klik tombol *"Atur Kuota"* pada salah satu cabang.
     - Ubah kuota (misal dari 50.000 menjadi 100.000 token) dengan preset 1-klik.
     - Tunjukkan bahwa perubahan langsung tersimpan ke sistem.
   - **Sub-Tab Log Aktivitas**:
     - Perlihatkan riwayat lengkap: user, cabang, pertanyaan, SQL, JSON filter, dan durasi eksekusi hingga level milidetik.

---

## 4. Antisipasi Pertanyaan Dosen Penguji / Pembimbing PKL

### Q1: *"Kenapa tidak menggunakan LLM generatif langsung untuk membuat SQL tanpa composer/verifier?"*
> **Jawaban**:  
> *"LLM generatif murni memiliki tingkat halusinasi skema sebesar 20-30% pada database industri yang memiliki ribuan tabel. Selain itu, LLM murni tidak menjamin bahwa SQL yang dihasilkan bersifat Read-Only. Di DMS AI Platform, kami menerapkan arsitektur dua tier dengan 6 gerbang verifikasi AST (default-deny), sandboxing timeout 10 detik, dan limit 500 baris. Ini adalah standar keamanan enterprise mutlak agar database operasional dealer tidak pernah terganggu."*

### Q2: *"Bagaimana sistem menjamin angka dalam teks ringkasan tidak dikarang oleh AI?"*
> **Jawaban**:  
> *"Kami membangun modul Presenter dengan mekanisme NUMBER CHECK mekanis. Setiap angka nominal yang ditulis oleh LLM dalam ringkasan naratif wajib dicek kecocokannya terhadap baris data SQL riil. Jika ada satu angka pun yang tidak ada di hasil query (halusinasi), narasi langsung dibatalkan secara otomatis dan digantikan oleh ringkasan template deterministik berbasis data riil."*

### Q3: *"Bagaimana sistem mengontrol biaya token OpenAI/Claude/Groq agar tidak membengkak?"*
> **Jawaban**:  
> *"Pertama, skema database dipadatkan (hanya tabel relevan yang diizinkan lewat skema efektif). Kedua, kami menerapkan SQL Memory Replay sehingga pertanyaan yang sudah disetujui pengguna diputar ulang dengan 0 token. Ketiga, di sisi admin kami mengimplementasikan penegakan kuota token harian per cabang (default 50.000 token) yang dapat dipantau dan diatur secara real-time."*

---

## 5. Checklist Verifikasi Sebelum Masuk Ruang Sidang

- [ ] Docker container PostgreSQL berjalan (`docker compose ps` port 5433).
- [ ] Database host tenant aktif di port 5432.
- [ ] Backend FastAPI aktif di port 8000 (`.venv\Scripts\python.exe -m uvicorn app.main:app`).
- [ ] Frontend Vite aktif di port 5173 (`npm run dev`).
- [ ] Akun `admin/admin123` dan `tester01/tester123` dapat login tanpa kendala.
- [ ] Satu file ekspor Excel sampel sudah pernah diunduh dan dipastikan membuka chart di MS Excel.
- [ ] Browser Chrome sudah dalam kondisi zoom 100% dengan tampilan rapi.
