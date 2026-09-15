# Analisis Domain Bisnis Dealer & Bengkel Berdasarkan Peran (Role-Based AI Reporting)

> **Sumber Rujukan**: Shared Discussion ChatGPT — [Analisis Penjualan Bengkel](https://chatgpt.com/share/6aa7a0a7-726c-83ec-9da1-ef4453f5e354)  
> **Tujuan Dokumen**: Menjadi panduan domain knowledge otomotif dealer 3S (Sales, Service, Sparepart) dalam merancang persona, batasan KPI, sudut pandang analitik (*insight generation*), dan izin data untuk 7 Role Bisnis di DMS AI Platform (Fase C & F Revisi v3).

---

## 0. Filosofi Utama: Satu Data, Beragam Sudut Pandang

Dalam ekosistem dealer otomotif terpadu, satu peristiwa data (misalnya: *penjualan mobil turun 10%*) memiliki arti dan tindakan lanjutan yang sangat berbeda bagi masing-masing jabatan:

| Role / Jabatan | Pertanyaan Utama yang Dicari Jawabannya |
|---|---|
| **Sales Supervisor** | *"Salesman mana yang penjualannya merosot atau targetnya tidak tercapai?"* |
| **Sales Manager** | *"Model mana yang macet? Di cabang mana? Kenapa conversion funnel terhambat?"* |
| **Service Manager** | *"Berapa unit entry hari ini? Bagaimana utilisasi stall/teknisi dan retensi servis berkala?"* |
| **Finance Manager** | *"Bagaimana dampaknya ke cash flow, gross margin, diskon unit, dan umur piutang (AR)?"* |
| **Accounting Manager** | *"Apakah seluruh transaksi sudah di-invoice, COGS tercatat benar, dan terealisasi/rekonsiliasi tanpa selisih?"* |
| **Admin Head** | *"Di mana dokumen/transaksi yang nyangkut? Berapa SPK/RO pending dan apakah melewati SLA?"* |
| **Direksi (Board of Directors)** | *"Bagaimana kesehatan bisnis secara holistik? Keputusan strategis apa yang harus diambil?"* |

---

## 1. Analisis Peran: Direksi (Executive & Board of Directors)

Direksi tidak berfokus pada mikro-operasional perorangan, melainkan pada **kesehatan bisnis holistik**, profitabilitas riil, kecepatan perputaran modal, dan performa antar-cabang.

### 1.1. Mesin 1: Penjualan Mobil (Vehicle Sales)

1. **Sales Performance Macro**:
   - Target vs Actual (Volume Unit & Revenue).
   - Achievement Rate (%) dan Pertumbuhan (Growth MoM & YoY).
   - Komparasi Antar-Cabang dan Antar-Wilayah.
   - Komposisi Penjualan: Retail vs Fleet (Korporasi).
   - Laju Konversi Siklus Penjualan: Booking $\rightarrow$ SPK $\rightarrow$ Delivery / DO.
   - Cancellation Rate (Tingkat pembatalan pesanan).
2. **Product & Model Performance**:
   - Model mana yang overperform (tulang punggung omzet) vs underperform (beban stok).
   - Kontribusi per model terhadap total laba (unit terlaris belum tentu menghasilkan margin tertinggi).
   - Average Selling Price (ASP) dan rata-rata margin keuntungan per model.
3. **Sales Conversion Funnel**:
   - $\text{Leads} \xrightarrow{\text{conv \%}} \text{Prospect} \xrightarrow{\text{conv \%}} \text{Test Drive} \xrightarrow{\text{conv \%}} \text{SPK} \xrightarrow{\text{conv \%}} \text{Delivery}$.
   - Lokalisasi *bottleneck*: Jika leads tinggi tapi Test Drive $\rightarrow$ SPK anjlok, masalah bukan di promosi/marketing, melainkan di harga, diskon kompetitor, atau tenaga penjual.
4. **Financing & Leasing Penetration**:
   - Rasio Cash vs Credit (umumnya 70–80% pembelian dealer via kredit).
   - Penetrasi Leasing Partner: Approval rate, rejection rate, dan insentif refund dari leasing.
5. **Stock & Inventory Health**:
   - Stock Aging & Days of Inventory (DOI) per model dan tipe.
   - Identifikasi *Dead Stock* dan *Slow Moving Units* (modal kerja dealer yang tertahan di garasi/gudang).
   - Inventory Turnover Ratio.

### 1.2. Mesin 2: Bengkel & Layanan Purna Jual (After-Sales & Service)

1. **Workshop Performance**:
   - Total Unit Entry / Repair Order (RO) masuk.
   - Struktur Pendapatan Bengkel: Jasa Teknisi (*Labor*), Suku Cadang (*Parts*), Bahan/Oli, dan Aksesoris.
   - Kategori Pekerjaan: Perawatan Berkala (*Periodic Maintenance*), Perbaikan Umum (*General Repair*), Klaim Garansi (*Warranty*), dan *Body & Paint*.
   - Average RO Value (Nilai rata-rata uang yang dibelanjakan per mobil masuk).
2. **Workshop Productivity & Capacity**:
   - Technician Efficiency & Utilization (Rasio jam kerja produktif vs jam kerja tersedia).
   - Bay / Stall Utilization Rate.
3. **Parts Supply & Fill Rate**:
   - Tingkat ketersediaan sparepart (*fill rate* & *backorder*). Ketiadaan part menyebabkan servis tertunda dan kepuasan pelanggan jatuh.
4. **Customer Retention & Loyalty**:
   - Service Retention Rate: Berapa persen pembeli mobil baru yang kembali servis di bengkel resmi setelah 6, 12, 24 bulan.
   - Customer Lifetime Value (CLV) & Inactive Customer Count.
5. **Customer Satisfaction**:
   - Customer Satisfaction Index (CSI) & Net Promoter Score (NPS).
   - Jumlah keluhan (*complaints*) dan SLA resolusi komplain.

### 1.3. Struktur Hierarki & Contoh Insight AI Direksi

```
                    DEALER PERFORMANCE (DIREKSI)
                                 │
          ┌──────────────────────┴──────────────────────┐
          │                                             │
     SALES UNIT                                    AFTER SALES
          │                                             │
    ┌─────┼─────────┐                             ┌─────┼─────────┐
    │     │         │                             │     │         │
 Target Model    Inventory                    Workshop Suku Cadang Pelanggan
   vs     &      & Leasing                     (RO &    (Stok &   (Retensi &
 Actual Margin     Aging                      Revenue) Fill Rate)    CSI)
```

> **Contoh Karakter Insight AI untuk Direksi**:  
> *"Total penjualan unit bulan ini 380 unit (76% target). Penurunan terbesar berasal dari Model B (-21% MoM). Namun leads stabil, hambatan berada pada konversi Test Drive ke SPK yang turun dari 35% ke 22% akibat promo kompetitor. Cabang Bogor menyumbang defisit terbesar. Rekomendasi: evaluasi diskon taktikal Model B dan relokasi 15 unit dead stock cabang Bogor ke cabang Depok."*

---

## 2. Analisis Peran: Finance Manager

Finance Manager berfokus pada **aliran uang (cash flow), likuiditas, profitabilitas riil, pengelolaan modal kerja, dan mitigasi risiko piutang/utang**.

### 2.1. Area Analisis Kunci Finance

1. **Struktur Total Revenue & Kontribusi**:
   - Pemisahan sumber pendapatan: Unit Kendaraan, Jasa Bengkel, Suku Cadang, Aksesoris, Asuransi, Insentif Pembiayaan (*Financing Incentive / Refund*).
2. **Gross Margin & Perbandingan Profitabilitas Divisi**:
   - Margin Unit Penjualan (biasanya tipis, berkisar 5%–10%).
   - Margin Bengkel & Suku Cadang (jauh lebih tebal, berkisar 35%–50%).
   - Pemahaman bahwa bengkel sering kali merupakan penyelamat arus kas saat pasar mobil lesu.
3. **Analisis Diskon (Discount Erosion Analysis)**:
   - Dampak perang diskon salesman/cabang terhadap tergerusnya laba kotor (*gross profit*).
   - Menghitung apakah peningkatan volume unit sebanding dengan diskon yang diobral.
4. **Analisis Biaya Operasional (Operating Expense & Variance)**:
   - Actual vs Budget: Beban gaji/komisi, biaya sewa showroom, listrik, promosi/marketing.
5. **Cash Flow & Likuiditas (Inflow vs Outflow)**:
   - Cash In (Pelunasan customer, pencairan leasing, penerimaan kas bengkel, klaim asuransi).
   - Cash Out (Penebusan unit ke ATPM/APM, pembelian stok sparepart, operasional, pajak).
   - Net Cash Flow harian & mingguan.
6. **Manajemen Piutang (Accounts Receivable / AR)**:
   - Total piutang outstanding dan klasifikasi umur piutang (*aging buckets*): 0–30 hari, 31–60 hari, 61–90 hari, dan >90 hari (kritis).
   - Piutang leasing yang belum cair (*unsettled leasing*) vs piutang pelanggan korporasi/fleet.
7. **Manajemen Utang (Accounts Payable / AP)**:
   - Utang pembelian unit ke APM, utang supplier sparepart, dan tanggal jatuh tempo (*due dates*).
8. **Nilai Modal Tertahan di Persediaan (Inventory Valuation)**:
   - Menghitung biaya modal (*holding cost*) dari unit mobil dan suku cadang yang menumpuk di gudang.

### 2.2. Struktur Dashboard & Contoh Insight AI Finance Manager

```
FINANCE MANAGER
├── PROFITABILITY: Gross Profit, Net Margin, Margin per Model, Margin per RO
├── SALES FINANCE: Revenue, Diskon Unit, COGS Unit, Komisi & Insentif
├── WORKSHOP FINANCE: Revenue Jasa vs Part, Cost of Labor/Part, Workshop Margin
├── CASH & LIQUIDITY: Cash Inflow, Cash Outflow, Net Cash Flow, Working Capital
├── AR AGING: Piutang Leasing, Piutang Customer, Aging >60 & >90 Hari
├── AP AGING: Utang APM, Utang Supplier Part, Jatuh Tempo
└── INVENTORY VALUE: Total Modal Tertahan, Holding Cost, Dead Stock Value
```

> **Contoh Karakter Insight AI untuk Finance Manager**:  
> *"Revenue bulan berjalan Rp 18,2 Miliar (94% budget). Namun laba kotor hanya tercapai 86% akibat diskon rata-rata unit melonjak 21% MoM. Di sektor bengkel, pendapatan jasa naik 8%, namun biaya pembelian part naik 15% sehingga margin bengkel tertekan dari 41% ke 37%. Total piutang Rp 3,2 Miliar, dengan Rp 450 Juta berstatus overdue >60 hari pada 2 leasing rekanan. Prioritas: penagihan AR leasing dan penghentian diskon tambahan Model B."*

---

## 3. Analisis Peran: Accounting Manager

Accounting Manager berfokus pada **kepatuhan pencatatan, akurasi jurnal, validitas saldo buku besar, rekonsiliasi antar-sistem, pencegahan anomali/fraud, dan kepatuhan perpajakan**.

### 3.1. Area Analisis Kunci Accounting

1. **Rekonsiliasi Pendapatan (Revenue Reconciliation)**:
   - Mencocokkan data transaksi operasional vs faktur vs buku besar: $\text{Sistem Sales / DMS} \longleftrightarrow \text{Faktur Penjualan} \longleftrightarrow \text{General Ledger}$.
   - Mendeteksi transaksi unit atau servis yang sudah selesai tetapi belum di-posting menjadi pendapatan (*unbilled / unposted revenue*).
2. **Ketepatan Periode (Cut-off & Period Closing)**:
   - Menjamin transaksi akhir bulan tidak bocor antar-periode (misal: unit dikirim tanggal 31, faktur baru dibuat tanggal 1 bulan berikutnya).
3. **Akurasi HPP / COGS (Cost of Goods Sold)**:
   - Validasi nilai pokok kendaraan (harga tebus APM, ongkos angkut, PPN, PPh pasal 22).
   - Validasi COGS suku cadang dan alokasi biaya tenaga kerja langsung bengkel.
4. **Rekonsiliasi Persediaan (Stock Opname vs Buku Besar)**:
   - Rekonsiliasi $\text{Fisik Gudang} \longleftrightarrow \text{Sistem Inventori} \longleftrightarrow \text{Saldo Buku Besar (GL)}$.
   - Penelusuran selisih barang hilang, salah input, atau rusak (*inventory variance & write-off*).
5. **Rekonsiliasi Pencairan Leasing & Bank**:
   - Mencocokkan SPK disetujui $\rightarrow$ Delivery $\rightarrow$ Tagihan Leasing $\rightarrow$ Rekening Koran Bank.
   - Mendeteksi selisih biaya administrasi bank, potongan provisi leasing, atau transfer tertunda.
6. **Akuntansi Klaim Garansi (Warranty Claims Accounting)**:
   - Memonitor status pengajuan klaim garansi ke pabrikan: Diajukan $\rightarrow$ Disetujui $\rightarrow$ Ditolak $\rightarrow$ Dibayarkan.
   - Klaim garansi yang ditolak pabrikan harus segera diakui sebagai biaya/kerugian bengkel.
7. **Pemeriksaan Pajak (Tax Compliance & Reconciliation)**:
   - Rekonsiliasi Faktur Pajak Keluaran (PPN 11%) vs Faktur Penjualan.
   - PPh Pasal 21 (komisi salesman/mekanik), PPh Pasal 23 (jasa vendor), dan PPh Pasal 22 (unit otomotif).
8. **Deteksi Anomali & Kontrol Internal (Fraud Detection)**:
   - Mendeteksi transaksi diskon di luar batas wewenang.
   - Jurnal manual tidak biasa (*unusual manual adjustments*), pembatalan faktur (*void*) berulang, atau duplikasi pembayaran ke vendor.

### 3.2. Struktur Dashboard & Contoh Insight AI Accounting Manager

```
ACCOUNTING MANAGER
├── RECONCILIATION
│   ├── Sales System vs Invoice vs General Ledger
│   ├── Workshop RO vs Invoice vs AR
│   ├── Bank Reconciliation (Bank Statement vs Cash Ledger)
│   └── Stock Opname Variance (Fisik vs Sistem)
├── COGS & INVENTORY
│   ├── Vehicle COGS Accuracy & Margin Matching
│   ├── Parts COGS & Inventory Valuation
│   └── Slow Moving & Dead Stock Reserve
├── CLOSING & CUT-OFF
│   ├── Unbilled / Unposted Transactions
│   ├── Revenue Recognition Timing
│   └── Month-End Closing Readiness
├── COMPLIANCE & TAX
│   ├── VAT Output vs Sales Invoices
│   ├── Withholding Taxes (PPh 21/22/23)
│   └── Warranty Claims Approval & Rejection
└── INTERNAL CONTROL & AUDIT
    ├── Abnormal Discounts & Threshold Breaches
    ├── Manual Journal Vouchers
    └── Repeated Void / Canceled Invoices
```

> **Contoh Karakter Insight AI untuk Accounting Manager**:  
> *"Ditemukan selisih rekonsiliasi: 3 unit kendaraan senilai Rp 870 Juta berstatus terkirim (DO) pada akhir bulan namun belum terbit faktur penjualan. Pada modul bengkel, terdapat 14 RO selesai senilai Rp 32 Juta yang belum di-posting ke pendapatan. Klaim garansi bulan ini sebesar Rp 45 Juta ditolak oleh APM dan perlu penyesuaian biaya. Ditemukan 6 transaksi diskon melebihi wewenang standar cabang tanpa approval tertulis."*

---

## 4. Analisis Peran: Admin Head

Admin Head bertanggung jawab atas **kelancaran dokumen, tata kelola alur kerja administratif, kepatuhan SOP, kecepatan proses (SLA), penuntasan berkas tersendat (backlog), dan kualitas database**.

### 4.1. Area Analisis Kunci Admin Head

1. **Sales Administrative Pipeline & Monitoring**:
   - Memantau alur berkas: $\text{SPK Masuk} \rightarrow \text{Verifikasi Berkas} \rightarrow \text{Survey/Approval Leasing} \rightarrow \text{PO Leasing} \rightarrow \text{Faktur} \rightarrow \text{Pelunasan} \rightarrow \text{DO} \rightarrow \text{STNK/BPKB}$.
   - Mendeteksi SPK gantung (*pending approval*), SPK batal, dan transaksi yang pembayarannya belum lengkap.
2. **Kelengkapan Dokumen Pelanggan (Document Completeness)**:
   - Persentase kelengkapan berkas: KTP, Kartu Keluarga, NPWP, Form SPK bertandatangan, Bukti Bayar, PO Leasing.
   - Mendeteksi transaksi yang unitnya sudah diserahkan (*delivered*) tetapi dokumennya belum lengkap.
3. **Monitoring Pengurusan Dokumen Kendaraan (STNK & BPKB)**:
   - Memantau berkas faktur polisi, pendaftaran Samsat, hingga STNK & BPKB diserahkan ke pelanggan.
   - Menghitung aging pengurusan STNK (peringatan bila melewati SLA standar 14 hari kerja).
4. **Konsistensi Status Kendaraan (Vehicle Administrative Status)**:
   - Mencari anomali status sistem:
     - Unit tercatat sudah diserahkan (*Delivered*), tetapi status faktur masih belum dibuat.
     - Unit tercatat laku (*Sold*), namun di daftar persediaan fisik masih berstatus bebas (*Available*).
5. **Administrasi Bengkel & Monitoring Work Order (RO)**:
   - Memantau status RO: Open $\rightarrow$ Pending $\rightarrow$ Invoiced $\rightarrow$ Paid $\rightarrow$ Vehicle Out.
   - Menelusuri penyebab RO gantung (*pending*): menunggu part inden, belum ada persetujuan estimasi biaya dari pemilik, atau klaim asuransi belum disetujui.
6. **Kualitas Master Data (Data Hygiene & Quality Control)**:
   - Mendeteksi nomor telepon kosong/tidak valid pada master customer.
   - Mendeteksi duplikasi data customer atau duplikasi nomor rangka (*VIN*) kendaraan.
7. **Analisis SLA & Produktivitas Tim Admin**:
   - Rata-rata durasi pemrosesan berkas per admin: SPK ke Faktur, Faktur ke DO, Pengajuan Leasing ke PO.
   - Beban kerja antar-staf admin (*workload balancing*) dan rasio berkas revisi/salah input (*rework rate*).

### 4.2. Struktur Dashboard & Contoh Insight AI Admin Head

```
ADMIN HEAD
├── SALES ADMIN & PIPELINE
│   ├── SPK Monitoring (Pending, Approved, Canceled)
│   ├── Delivery Pending (Pembayaran lunas tapi belum DO)
│   └── Dokumen Kendaraan (Aging STNK/BPKB & Pelanggaran SLA)
├── DOCUMENT COMPLIANCE
│   ├── Kelengkapan Berkas (KTP, KK, NPWP, PO Leasing)
│   └── BAST & Berita Acara Serah Terima Unit
├── WORKSHOP ADMIN
│   ├── RO Pending (Menunggu part, menunggu approval customer)
│   ├── RO Selesai tapi Belum Terbit Invoice
│   └── Invoice Terbit tapi Kasir Belum Terima Pembayaran
├── SLA & PROCESS BOTTLENECK
│   ├── Rata-rata Waktu Proses SPK ke DO
│   ├── Transaksi Melewati Batas Waktu (Overdue SLA)
│   └── Hambatan Antar-Departemen (Sales vs Admin vs Leasing)
└── DATA QUALITY & EXCEPTION
    ├── Anomali Status Kendaraan (Delivered vs Stock Inconsistent)
    ├── Pelanggan Duplikat & Kontak Tidak Valid
    └── Tingkat Kesalahan Input Dokumen (Rework Rate)
```

> **Contoh Karakter Insight AI untuk Admin Head**:  
> *"Terdapat 38 berkas administrasi berstatus pending (naik 15% minggu ini). 18 transaksi tertahan menunggu PO leasing, dan 11 unit sudah siap kirim namun dokumen BAST belum lengkap. Sebanyak 8 pengurusan STNK telah melewati SLA 14 hari kerja pada Biro Jasa X. Di divisi servis, terdapat 19 RO berstatus pekerjaan selesai namun belum dicetak invoicenya. Ditemukan 14 data customer baru dengan kontak telepon kosong."*

---

## 5. Ringkasan Perbandingan Karakteristik 7 Role

| Role / Jabatan | Cakupan Data Pokok | KPI / Metrik Kunci | Tindakan Utama dari Insight AI |
|---|---|---|---|
| **Direksi** | Seluruh Perusahaan & Cabang (3S) | Volume, Revenue, Profit Margin, Growth YoY, CSI, Cash Flow | Keputusan strategis, alokasi modal, target cabang |
| **Sales Manager** | Divisi Penjualan Unit | Target vs Actual, Model Share, Conversion Funnel, Cancellation | Strategi promosi, evaluasi tipe mobil, pipeline sales |
| **Sales Supervisor** | Tim Salesman Cabang | SPK per Salesman, Leads to Prospect, Aktivitas Harian | Coaching salesman, distribusi prospek, mitigasi SPK batal |
| **Service Manager** | Divisi Bengkel & Part | Unit Entry, Jasa Bengkel, Part Sales, Stall Utilization, Retensi | Efisiensi mekanik, jam kerja servis, kepuasan servis |
| **Finance Manager** | Keuangan & Arus Kas | Net Margin, Diskon Unit, Cash Flow, AR/AP Aging, Inventory Value | Penagihan leasing, batas diskon, likuiditas modal |
| **Accounting Manager** | Pembukuan & Kepatuhan | Rekonsiliasi DMS vs GL, COGS, Stock Opname, Pajak, Anomali | Jurnal koreksi, investigasi selisih, closing bulanan |
| **Admin Head** | Alur Dokumen & SLA | SPK Pending, STNK Aging, Backlog RO, Kelengkapan Berkas, SLA | Penuntasan berkas macet, follow-up biro jasa/leasing |

---

## 6. Implikasi Arsitektur pada DMS AI Platform (v3)

1. **Role-Based Access Control (RBAC) pada Fase C**:
   - Pembatasan tabel (`allowed_tables`) dan kolom (`denied_columns`) harus disesuaikan secara ketat dengan profil tugas di atas.
   - *Finance/Accounting*: Diberikan akses kolom moneter sensitif (`hjpokok`, `cogs`, `diskon`, `ar_aging`), tetapi dibatasi dari akses data pribadi tidak relevan.
   - *Admin Head*: Diberikan akses tabel transaksi dan dokumen operasional (`untt_pesanankendaraan`, `glbm_customer`, `srvt_wo`), tetapi kolom margin moneter rahasia disembunyikan.
2. **Contextual Suggestion Chips (Fase F)**:
   - Rekomendasi kueri lanjutan (*chips*) di bawah kartu jawaban tidak boleh sama untuk semua pengguna.
   - Jika login sebagai **Finance Manager**, kueri lanjutan berorientasi pada laba, diskon, dan cash flow.
   - Jika login sebagai **Admin Head**, kueri lanjutan berorientasi pada backlog dokumen, SLA, dan status pending.
3. **Presenter & Narasi Analisis Adaptif (Fase F)**:
   - *Presenter* naratif AI harus mengadopsi struktur bahasa yang relevan:
     - **Eksekutif/Direksi**: Ringkas, menyoroti tren makro, persentase pertumbuhan, dan anomali cabang.
     - **Accounting**: Teliti, menyoroti selisih rekonsiliasi (*unbilled/unposted*), varians, dan kepatuhan akun.
     - **Admin Head**: Operasional, menyoroti jumlah item yang macet, nama dokumen, dan pelanggaran SLA hari.

---

## 7. Pemetaan Riil Database `demo_otobitzcloud` (2.387 Tabel) ke 7 Role

Berdasarkan inspeksi langsung terhadap database `demo_otobitzcloud` / `backup_demo_otobitzcloud` (2.387 tabel riil), berikut adalah matriks tabel dan kolom aktif yang siap digunakan untuk penegakan izin (Fase C RBAC) dan perancangan prompt kueri (Fase F):

### 7.1. Matriks Pemetaan Tabel Database Riil per Role

| Role / Jabatan | Kategori Analisis | Tabel Riil di Database | Jumlah Baris Riil | Kolom-Kolom Kunci & Catatan Skema |
|---|---|---|---|---|
| **Direksi** | Macro Sales & Revenue | `untt_penjualan` | 14.045 | `nomor`, `tanggal`, `hjunit`, `diskon`, `hjakhir`, `batal`, `retur` |
| | Performa Model Mobil | `untm_model`, `untm_tipe` | 74 & 27 | `kode`, `nama` (Brio, HR-V, CR-V, BR-V) |
| | Macro Workshop Servis | `srvt_wo`, `srvt_wodetail` | 138.738 & 927.136 | `nomor`, `tanggal`, `totalestimasibiaya`, `jasa`, `part`, `bahan` |
| | Customer CSI & Retention | `srv_vw_laporanservicephonesurvey` | 104.318 | `tglfaktur`, `namapemilik`, `nopolisi`, `tipeservice`, `kodesa` |
| | Komparasi Antar-Cabang | `glbm_cabang` | Master | `kode`, `nama` (filter lintas cabang) |
| **Finance Manager** | Piutang Usaha (AR Aging) | `cari_daftarumurpiutangsemuajenis` | 56 | `jenispiutang`, `tgljatuhtempo`, `selisihhari` (aging), `nilaipiutang`, `nilaipenerimaan` |
| | Utang Usaha (AP Aging) | `cari_daftarumurhutangsemuajenis` | 140 | `namasupplier`, `tgljatuhtempo`, `nilaihutang`, `nilaipembayaran`, `tgltransaksi` |
| | Tagihan & Piutang Leasing | `cari_tagihanleasing` | 14.046 | `nomor`, `nomor_pesanan`, `norangka`, `hjunit`, `diskon`, `hpbbn` |
| | Pencairan Kartu Kredit/Leasing | `srv_vw_pelunasanleasing`, `untt_pencairankartukredit` | 11.567 & 1.821 | `tanggal`, `nominal`, `bankcharge`, `leasing_id` |
| | Nilai Stok & HPP Sparepart | `srvt_stockparts` | Puluhan ribu | `stockawal`, `masuk`, `keluar`, `cogs`, `minstock` |
| **Accounting Manager** | Jurnal Transaksi Umum | `acctt_entrydatajournal`, `acctt_entrydatajournaldetail` | 8.599 & 29.754 | `nomor`, `tanggal`, `posting`, `userposting`, `tglvoucher`, `debet`, `kredit` |
| | Neraca Saldo Departemen | `acctt_trialbalancedepartemen` | 62.088 | `kode_akun`, `nama_akun`, `departemen`, `saldo_awal`, `mutasi_d`, `mutasi_k` |
| | Faktur Pajak PPN Keluaran | `TaxInvoice`, `TaxInvoice_ori` | 78.936 & 195.220 | `nomor_faktur`, `tanggal`, `dpp`, `ppn`, `status_faktur` |
| | Parameter Jurnal Otomatis | `acctm_interfacejournal`, `acctm_interfacejournalparameter` | 161 & 966 | `transaksi_tipe`, `kode_rekening_debet`, `kode_rekening_kredit` |
| | Penyusutan Aset Tetap | `acctt_generatepenyusutan` | 4.379 | `tglpenyusutan`, `nilai_buku`, `akumulasi_penyusutan` |
| **Admin Head** | SPK Belum Matching Unit | `spk_belummatching_dashboard` | 13.867 | `nomor`, `tanggal`, `nomor_customer`, `namapenerima`, `namastnk` |
| | Register & Riwayat SPK | `cari_listdataregistrasispk` | 22.753 | `nomorspk`, `tglspk`, `salesman`, `statusspk` |
| | Pengajuan STNK & BPKB | `srv_vw_cetak_orderpengajuanstnkbpkb` | 13.691 | `noappstnkbpkb`, `tglappstnkbpkb`, `norangka`, `namabirojasa`, `tipekendaraan` |
| | BPKB Selesai Leasing | `srv_vw_bpkbselesaileasing` | 8.996 | `nomor_bpkb`, `tglpenyerahan`, `leasing_nama`, `status_selesai` |
| | DO / Surat Jalan Unit Keluar | `srv_vw_cetak_suratjalangudangout` | 15.739 | `nosuratjalan`, `tanggalsuratjalan`, `norangka`, `nomesin` |
| | Permohonan Revisi SPK | `srv_vw_cetak_permohonanrevisispk` | 103.435 | `nomorspk`, `tglrevisi`, `alasanrevisi`, `status_approval` |
| **Sales Manager** | Kontrak Penjualan Unit | `untt_penjualan` | 14.045 | `nomor`, `tanggal`, `hjunit`, `diskon`, `hjakhir`, `batal = false` |
| | Pemesanan Kendaraan (SPK) | `untt_pesanankendaraan` | 13.867 | `nomor`, `tanggal`, `nomor_customer`, `dp`, `total`, `batal` |
| | Aplikasi Kredit Leasing | `untt_aplikasikredit`, `untt_historyaplikasikredit` | 9.062 & 5.545 | `noaplikasi`, `tglpengajuan`, `leasing`, `status_approval`, `tglsurvey` |
| **Sales Supervisor** | Kinerja Salesman | `untm_karyawan`, `api_salesmandata` | 63 & 1.183 | `kodesalesman`, `namasalesman`, `jabatan`, `status_aktif` |
| | Monitoring SPK Tim | `untt_pesanankendaraan`, `cari_listdataregistrasispk` | 13.867 & 22.753 | `nomor`, `salesman`, `dp`, `tanggal`, `batal` |
| **Service Manager** | Work Order / PKB Bengkel | `srvt_wo` | 138.738 | `nomor`, `tanggal`, `nopolisi`, `norangka`, `totalestimasibiaya`, `batal` |
| | Rincian Jasa & Part Servis | `srvt_wodetail` | 927.136 | `nomor_wo`, `jasa`, `part`, `bahan`, `nomor_tasklist` |
| | Data Mekanik Bengkel | `srvm_mechanic`, `srvm_foreman` | 67 & 8 | `kodemekanik`, `namamekanik`, `status` |
| | Penutupan WO (Closing Servis)| `cari_dataclosewo` | 690 | `nomor_wo`, `tglselesai`, `totalbayar`, `status_lunas` |
| | Pekerjaan Body Repair | `srvm_komposisibahanbody` | 2.406 | `kodepart`, `namabahan`, `kategori_perbaikan` |

---

### 7.2. Rancangan Izin Data RBAC (Fase C — `role_permissions`)

Berdasarkan pemetaan di atas, rancangan hak akses tabel dan kolom yang akan dimasukkan ke migrasi `017_rbac.sql` adalah:

1. **`direksi`**:
   - `allowed_tables`: Seluruh tabel analitik (`untt_penjualan`, `srvt_wo`, `srvt_wodetail`, `srvt_stockparts`, `cari_daftarumurpiutangsemuajenis`, `srv_vw_laporanservicephonesurvey`, `untm_model`, `glbm_cabang`).
   - `denied_columns`: Kosong (`[]` — akses penuh eksekutif).
   - `allowed_branches_mode`: `all` (seluruh cabang).
2. **`finance_manager`**:
   - `allowed_tables`: `untt_penjualan`, `srvt_wo`, `srvt_wodetail`, `srvt_stockparts`, `cari_daftarumurpiutangsemuajenis`, `cari_daftarumurhutangsemuajenis`, `cari_tagihanleasing`, `srv_vw_pelunasanleasing`.
   - `denied_columns`: `glbm_customer.alamat`, `glbm_customer.telp`, `glbm_customer.hp` (proteksi privasi).
   - `allowed_branches_mode`: `own` (atau `all` bila Finance Pusat).
3. **`accounting_manager`**:
   - `allowed_tables`: `acctt_entrydatajournal`, `acctt_entrydatajournaldetail`, `acctt_trialbalancedepartemen`, `TaxInvoice`, `TaxInvoice_ori`, `acctm_interfacejournal`, `untt_penjualan`, `srvt_wo`, `srvt_wodetail`.
   - `denied_columns`: `glbm_customer.alamat`, `glbm_customer.hp`.
   - `allowed_branches_mode`: `own`.
4. **`admin_head`**:
   - `allowed_tables`: `spk_belummatching_dashboard`, `cari_listdataregistrasispk`, `srv_vw_cetak_orderpengajuanstnkbpkb`, `srv_vw_bpkbselesaileasing`, `srv_vw_cetak_suratjalangudangout`, `srv_vw_cetak_permohonanrevisispk`, `untt_pesanankendaraan`, `srvt_wo`.
   - `denied_columns`: `untt_penjualan.hjpokok`, `srvt_stockparts.cogs`, `untt_pembelian.hpdpp`, `untt_pembelian.hpunit` (kolom margin moneter rahasia disembunyikan).
   - `allowed_branches_mode`: `own`.
5. **`sales_manager`**:
   - `allowed_tables`: `untt_penjualan`, `untt_pesanankendaraan`, `untt_aplikasikredit`, `untt_historyaplikasikredit`, `untm_model`, `untm_tipe`, `untm_karyawan`, `api_salesmandata`.
   - `denied_columns`: `untt_penjualan.hjpokok`, `untt_pembelian.hpunit` (margin dasar tersembunyi; hanya melihat omzet & diskon).
   - `allowed_branches_mode`: `own`.
6. **`sales_supervisor`**:
   - `allowed_tables`: `untt_penjualan`, `untt_pesanankendaraan`, `untm_karyawan`, `api_salesmandata`, `cari_listdataregistrasispk`.
   - `denied_columns`: `untt_penjualan.hjpokok`, `untt_penjualan.diskon_khusus`.
   - `allowed_branches_mode`: `own`.
7. **`service_manager`**:
   - `allowed_tables`: `srvt_wo`, `srvt_wodetail`, `srvt_stockparts`, `srvm_mechanic`, `srvm_foreman`, `cari_dataclosewo`, `srv_vw_laporanservicephonesurvey`, `srvm_komposisibahanbody`.
   - `denied_columns`: Seluruh tabel penjualan unit (`untt_*`).
   - `allowed_branches_mode`: `own`.

