// ==========================================================================
// MOCK: ganti dengan endpoint backend saat Fase 3
// ==========================================================================
// Seluruh data & simulasi "pipeline AI" di halaman chat user terkumpul di
// sini. Komponen UI TIDAK memuat data mock — cukup memanggil:
//
//   const answer = await askAssistant(question, { onStage: (i, stage) => ... });
//
// Saat Fase 3: pindahkan implementasi `askAssistant` ke services/api.js
// (mis. POST /chat dengan streaming), lalu pertahankan kontrak yang sama:
// `onStage` dipanggil bertahap, Promise resolve dengan objek AssistantAnswer
// (summary + table + chart). Komponen UI tidak perlu diubah.
// ==========================================================================

/** Konteks cabang user yang tampil di header (MOCK). */
export const MOCK_USER_CONTEXT = {
  branchCode: 'JKT_01',
  branchName: 'Dealer JKT_01',
  companyName: 'PT Mandiri Auto',
  period: 'Agustus 2026',
};

/** Chip pertanyaan saran di atas kolom input. */
export const SUGGESTED_QUESTIONS = [
  'Penjualan bulan ini',
  'Stok menipis',
  'Servis terjadwal minggu ini',
];

/** Tahapan pipeline yang disimulasikan (total ±1,5 detik). */
export const MOCK_PIPELINE_STAGES = [
  { key: 'understand', label: 'Memahami pertanyaan…', ms: 400 },
  { key: 'query', label: 'Menyusun query…', ms: 400 },
  { key: 'fetch', label: 'Mengambil data…', ms: 450 },
  { key: 'compose', label: 'Menyusun jawaban…', ms: 300 },
];

// --------------------------------------------------------------------------
// Basis data mock per topik (dealer). Semua nilai statis agar hasilnya
// deterministik — tidak ada random.
// --------------------------------------------------------------------------

const ANSWER_SALES = {
  summary:
    'Sepanjang Agustus 2026, Dealer JKT_01 menjual 117 unit dengan total nilai Rp 1,84 M — naik 12% dibanding bulan lalu. Model terlaris: Toyota Avanza (42 unit).',
  table: {
    title: 'Penjualan unit per model — Agustus 2026',
    columns: ['Model', 'Unit Terjual', 'Nilai (Rp)'],
    rows: [
      ['Toyota Avanza', '42', '612.000.000'],
      ['Honda Brio', '35', '472.000.000'],
      ['Toyota Xenia', '28', '364.000.000'],
      ['Toyota Innova', '12', '390.000.000'],
    ],
  },
  chart: {
    title: 'Unit terjual per model',
    unit: 'unit',
    data: [
      { label: 'Avanza', value: 42 },
      { label: 'Brio', value: 35 },
      { label: 'Xenia', value: 28 },
      { label: 'Innova', value: 12 },
    ],
  },
  source: 'db_sales_jkt01 · simulasi (MOCK)',
};

const ANSWER_STOCK = {
  summary:
    'Ada 4 model dengan stok di bawah ambang aman. Prioritas utama: Toyota Alphard (2 unit, kritis) dan Toyota Agya (3 unit) — segera ajukan purchase order.',
  table: {
    title: 'Stok di bawah ambang aman',
    columns: ['Model', 'Stok Tersisa', 'Ambang', 'Status'],
    rows: [
      ['Toyota Alphard', '2', '5', 'Kritis'],
      ['Toyota Agya', '3', '8', 'Menipis'],
      ['Honda Rush', '4', '8', 'Menipis'],
      ['Toyota Calya', '6', '10', 'Menipis'],
    ],
  },
  source: 'db_stock_jkt01 · simulasi (MOCK)',
};

const ANSWER_SERVICE = {
  summary:
    'Minggu ini ada 4 servis terjadwal di bengkel Dealer JKT_01. Semua slot mekanik tersedia; 1 servis membutuhkan suku cadang pre-order (kampas rem).',
  table: {
    title: 'Jadwal servis minggu ini',
    columns: ['Tanggal', 'Pelanggan', 'Jenis Servis', 'Mekanik'],
    rows: [
      ['Sen, 1 Sep', 'Budi Santoso', 'Servis berkala 10.000 km', 'Rizky'],
      ['Sel, 2 Sep', 'Sari Dewi', 'Ganti kampas rem', 'Andi'],
      ['Rab, 3 Sep', 'PT Logindo', 'Tune-up besar', 'Rizky'],
      ['Jum, 5 Sep', 'Ahmad Fauzi', 'Ganti oli & filter', 'Dewa'],
    ],
  },
  source: 'db_service_jkt01 · simulasi (MOCK)',
};

const FALLBACK_ANSWER = {
  summary:
    'Pertanyaan itu belum saya pahami (mode simulasi). Berikut ringkasan umum kinerja Dealer JKT_01 bulan ini — coba tanyakan penjualan, stok, atau servis.',
  table: {
    title: 'Ringkasan umum — Agustus 2026',
    columns: ['Metrik', 'Nilai'],
    rows: [
      ['Penjualan unit', '117 unit'],
      ['Nilai transaksi', 'Rp 1,84 M'],
      ['Servis selesai', '89'],
      ['Model stok menipis', '4'],
    ],
  },
  source: 'ringkasan umum · simulasi (MOCK)',
};

/** Pasangan kata kunci -> jawaban (urutan penting: dicek dari atas). */
const MOCK_ANSWERS = [
  { keywords: ['penjualan', 'jual', 'terjual', 'sales'], answer: ANSWER_SALES },
  { keywords: ['stok', 'inventory', 'persediaan', 'menipis'], answer: ANSWER_STOCK },
  { keywords: ['servis', 'service', 'bengkel', 'perawatan'], answer: ANSWER_SERVICE },
];

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Cari jawaban mock yang paling relevan dengan pertanyaan user. */
function pickAnswer(question) {
  const q = question.toLowerCase();
  const hit = MOCK_ANSWERS.find((entry) => entry.keywords.some((k) => q.includes(k)));
  return hit ? hit.answer : FALLBACK_ANSWER;
}

/**
 * MOCK: simulasi pipeline AI end-to-end.
 * Menjalankan tahapan `MOCK_PIPELINE_STAGES` satu per satu (memanggil
 * `onStage(i, stage)` di tiap awal tahap), lalu resolve dengan jawaban.
 * Fase 3: ganti isi fungsi ini dengan panggilan API backend.
 */
export async function askAssistant(question, { onStage } = {}) {
  for (let i = 0; i < MOCK_PIPELINE_STAGES.length; i += 1) {
    const stage = MOCK_PIPELINE_STAGES[i];
    onStage?.(i, stage);
    await delay(stage.ms);
  }

  const base = pickAnswer(question);
  return {
    id: `ans-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    question,
    createdAt: new Date().toISOString(),
    ...base,
  };
}
