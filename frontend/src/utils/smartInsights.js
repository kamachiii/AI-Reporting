/**
 * Smart Insights & Follow-up Suggestions Engine (Zero-Token).
 * 
 * Melakukan kalkulasi analitik matematis langsung di browser (tanpa LLM):
 * 1. Pertumbuhan / Perubahan tren (Δ%)
 * 2. Nilai Tertinggi & Terendah (Peak & Bottom performers)
 * 3. Total & Rata-rata
 * 4. Rekomendasi 3 pertanyaan lanjutan kontekstual berbasis domain otomotif
 */

const IDENTIFIER_KEYWORDS = [
  'nomor', 'kode', 'id', 'tahun', 'thn', 'year', 'bulan', 'bln',
  'month', 'tgl', 'tanggal', 'date', 'telepon', 'phone', 'telp', 'hp', 'nik', 'ktp',
];

const UANG_KEYWORDS = [
  'harga', 'omzet', 'omset', 'beli', 'jual', 'biaya', 'uang', 'dpp', 'ppn',
  'nominal', 'saldo', 'total_pembelian', 'total_penjualan', 'total_nilai',
  'hpunit', 'hpdpp', 'hpppn', 'hppbm', 'tarif', 'subtotal', 'diskon',
  'selisih', 'laba', 'rugi', 'profit', 'margin', 'pendapatan', 'piutang', 'hutang',
  'nilai_transaksi', 'total_transaksi', 'total_omzet', 'hjakhir',
];

function isIdentifierColumn(colName) {
  if (!colName) return false;
  const col = String(colName).toLowerCase();
  return IDENTIFIER_KEYWORDS.some((k) => col.includes(k));
}

function formatAngkaAtauUang(num, colName = '') {
  if (num === null || num === undefined || Number.isNaN(num)) return '0';
  const isUang = UANG_KEYWORDS.some((k) => String(colName).toLowerCase().includes(k))
    || Math.abs(num) >= 1000000;
  
  const absNum = Math.abs(num);

  if (isUang) {
    let formatted;
    if (absNum >= 1000000000) {
      formatted = `${(absNum / 1000000000).toFixed(2).replace(/\.00$/, '')} Miliar`;
    } else if (absNum >= 1000000) {
      formatted = `${(absNum / 1000000).toFixed(2).replace(/\.00$/, '')} Juta`;
    } else {
      formatted = new Intl.NumberFormat('id-ID').format(Math.round(absNum));
    }
    return `${num < 0 ? '-Rp ' : 'Rp '}${formatted}`;
  }

  return new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 }).format(num);
}

/**
 * Hitung metrik ringkas matematis dari data tabel (Zero-Token).
 */
export function hitungSmartInsights(columns, rows) {
  if (!columns || !rows || rows.length < 2) {
    return { hasInsights: false };
  }

  // Cari kolom metrik (numerik, bukan kolom identitas/tahun)
  let metricColIdx = -1;
  let metricColName = '';

  // Cari kolom kategori/label (biasanya nama, tahun, atau teks)
  let categoryColIdx = -1;
  let categoryColName = '';

  columns.forEach((col, idx) => {
    const isId = isIdentifierColumn(col);
    const sampleVal = Array.isArray(rows[0]) ? rows[0][idx] : rows[0]?.[col];
    const isNumeric = typeof sampleVal === 'number' || (!Number.isNaN(Number(sampleVal)) && sampleVal !== '');

    if (isNumeric && !isId && metricColIdx === -1) {
      metricColIdx = idx;
      metricColName = col;
    } else if (categoryColIdx === -1 && (!isNumeric || String(col).toLowerCase().includes('tahun'))) {
      categoryColIdx = idx;
      categoryColName = col;
    }
  });

  // Jika tidak ada kolom non-id yang numerik, fallback ke kolom angka mana pun
  if (metricColIdx === -1) {
    columns.forEach((col, idx) => {
      const sampleVal = Array.isArray(rows[0]) ? rows[0][idx] : rows[0]?.[col];
      const isNumeric = typeof sampleVal === 'number' || (!Number.isNaN(Number(sampleVal)) && sampleVal !== '');
      if (isNumeric && metricColIdx === -1 && !String(col).toLowerCase().includes('id')) {
        metricColIdx = idx;
        metricColName = col;
      }
    });
  }

  if (metricColIdx === -1) {
    return { hasInsights: false };
  }

  // Ekstrak data
  const parsedData = rows.map((r, i) => {
    const rawVal = Array.isArray(r) ? r[metricColIdx] : r?.[metricColName];
    const rawCat = categoryColIdx !== -1
      ? (Array.isArray(r) ? r[categoryColIdx] : r?.[categoryColName])
      : `Baris ${i + 1}`;
    const num = Number(rawVal);
    return {
      label: String(rawCat || `Data ${i + 1}`),
      value: Number.isNaN(num) ? 0 : num,
    };
  });

  // Urutkan untuk mencari tertinggi dan terendah
  const sorted = [...parsedData].sort((a, b) => b.value - a.value);
  const tertinggi = sorted[0];
  const terendah = sorted[sorted.length - 1];

  // Hitung total dan rata-rata
  const total = parsedData.reduce((acc, curr) => acc + curr.value, 0);
  const rataRata = total / parsedData.length;

  // Cek apakah ada perubahan tren (Δ%) jika berurutan (misal perbandingan 2 periode)
  let deltaPersen = null;
  let arahTren = 'sama'; // 'naik' | 'turun' | 'sama'

  if (parsedData.length >= 2) {
    const valAwal = parsedData[0].value;
    const valAkhir = parsedData[parsedData.length - 1].value;

    if (valAwal !== 0) {
      const delta = ((valAkhir - valAwal) / Math.abs(valAwal)) * 100;
      deltaPersen = delta.toFixed(1).replace(/\.0$/, '');
      if (delta > 0) arahTren = 'naik';
      else if (delta < 0) arahTren = 'turun';
    }
  }

  return {
    hasInsights: true,
    metricName: metricColName.replace(/_/g, ' '),
    totalFormatted: formatAngkaAtauUang(total, metricColName),
    rataRataFormatted: formatAngkaAtauUang(rataRata, metricColName),
    tertinggi: {
      label: tertinggi.label,
      nilaiFormatted: formatAngkaAtauUang(tertinggi.value, metricColName),
    },
    terendah: {
      label: terendah.label,
      nilaiFormatted: formatAngkaAtauUang(terendah.value, metricColName),
    },
    deltaPersen,
    arahTren,
    jumlahData: parsedData.length,
  };
}

/**
 * Hasilkan 3 rekomendasi pertanyaan lanjutan relevan berdasarkan konteks kueri (Zero-Token).
 */
export function buatRekomendasiPertanyaan(question = '', columns = [], rows = [], sql = '') {
  const qLower = question.toLowerCase();
  const sqlLower = (sql || '').toLowerCase();
  const colStr = (columns || []).join(' ').toLowerCase();
  const hasRows = (rows || []).length > 0;

  // Ekstrak tahun jika ada di pertanyaan, data kolom, atau sql
  let tahun = '2025';
  const matchTahun = qLower.match(/\b(20\d\d)\b/) || sqlLower.match(/\b(20\d\d)\b/) || colStr.match(/\b(20\d\d)\b/);
  if (matchTahun) {
    tahun = matchTahun[1];
  }

  // 1. Kategori: Customer / Pelanggan
  if (qLower.includes('customer') || qLower.includes('pelanggan') || sqlLower.includes('glbm_customer') || colStr.includes('customer')) {
    if (!hasRows) {
      return [
        `Tampilkan daftar seluruh customer aktif`,
        `Siapa 5 customer dengan transaksi terbanyak di tahun ${tahun}?`,
        `Tampilkan kota dengan jumlah customer terbanyak`,
      ];
    }
    return [
      `Berapa total nilai transaksi dari customer teratas di tahun ${tahun}?`,
      `Tampilkan jenis mobil yang paling sering dibeli oleh pelanggan`,
      `Bandingkan kontribusi 5 customer teratas dengan total omzet ${tahun}`,
    ];
  }

  // 2. Kategori: Servis / Bengkel / WO
  if (qLower.includes('servis') || qLower.includes('bengkel') || qLower.includes('wo') || sqlLower.includes('womt_wo')) {
    return [
      `Berapa perbandingan pendapatan jasa servis vs sparepart di tahun ${tahun}?`,
      `Tampilkan 5 mekanik dengan jumlah pengerjaan WO terbanyak`,
      `Tampilkan daftar jenis pekerjaan servis yang paling sering dilakukan`,
    ];
  }

  // 3. Kategori: Sparepart / Stok Gudang
  if (qLower.includes('part') || qLower.includes('sparepart') || qLower.includes('stok') || sqlLower.includes('invt_')) {
    return [
      `Tampilkan 5 sparepart dengan stok paling sedikit di gudang saat ini`,
      `Berapa total nilai pembelian sparepart dari supplier di tahun ${tahun}?`,
      `Tampilkan suku cadang yang paling sering digunakan dalam perawatan berkala`,
    ];
  }

  // 4. Kategori: Penjualan Unit / Omzet / Mobil
  if (qLower.includes('jual') || qLower.includes('omzet') || qLower.includes('unit') || qLower.includes('mobil') || sqlLower.includes('untt_penjualan')) {
    return [
      `Tampilkan breakdown total penjualan per bulan di tahun ${tahun}`,
      `Siapa 5 customer dengan total pembelian terbesar di tahun ${tahun}?`,
      `Bandingkan penjualan semester 1 dan semester 2 di tahun ${tahun}`,
    ];
  }

  // Fallback Umum
  return [
    `Bandingkan performa transaksi dengan tahun sebelumnya`,
    `Tampilkan 5 transaksi terbesar yang tercatat di database`,
    `Tampilkan ringkasan performa penjualan per kuartal di tahun ${tahun}`,
  ];
}
