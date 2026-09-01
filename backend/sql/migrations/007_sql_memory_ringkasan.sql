-- 007: Presenter F2.5 - kolom ringkasan & saran pada sql_memory
--
-- Menyimpan hasil presenter (ringkasan laporan maks 2 kalimat + saran
-- pertanyaan lanjutan) agar replay SQL Memory dapat memakai ulang
-- ringkasan TANPA panggilan LLM lagi. Entri lama bernilai NULL dan akan
-- mengisi dirinya sendiri (self-heal) pada replay berikutnya.
--
-- Catatan migrasi (konvensi repo):
--   - komentar TIDAK memakai titik-koma di tengah kalimat (init_db
--     memecah file SQL per karakter titik-koma)
--   - idempotent: ADD COLUMN IF NOT EXISTS, aman dijalankan berulang
--   - rollback manual tersedia di 007_sql_memory_ringkasan_rollback.sql

ALTER TABLE sql_memory ADD COLUMN IF NOT EXISTS ringkasan TEXT;

ALTER TABLE sql_memory ADD COLUMN IF NOT EXISTS saran JSONB;
