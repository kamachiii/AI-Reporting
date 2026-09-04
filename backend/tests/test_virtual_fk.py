"""Tests untuk Virtual Foreign Keys (relasi_tabel) pada Knowledge Base & SQL Composer."""
import pytest
from app.services.knowledge_base import validate_kb, suntikkan_relasi_ke_skema, parse_stored_kb
from app.services.sql_composer import compose_sql, SqlComposerError


class TestVirtualForeignKey:
    def test_validate_kb_relasi_tabel_valid(self):
        payload = {
            "relasi_tabel": [
                {
                    "tabel": "untt_pembelian",
                    "kolom": "norangka",
                    "merujuk_tabel": "untt_datakendaraan",
                    "merujuk_kolom": "norangka",
                },
                {
                    "tabel": "untt_penjualan",
                    "kolom": "kode_customer",
                    "merujuk_tabel": "glbm_customer",
                    "merujuk_kolom": "nomor",
                }
            ]
        }
        clean, errors = validate_kb(payload)
        assert errors == []
        assert len(clean["relasi_tabel"]) == 2
        assert clean["relasi_tabel"][0]["tabel"] == "untt_pembelian"
        assert clean["relasi_tabel"][0]["merujuk_tabel"] == "untt_datakendaraan"

    def test_validate_kb_relasi_tabel_invalid(self):
        # 1. Bukan list
        _, errors = validate_kb({"relasi_tabel": "bukan list"})
        assert any("harus berupa array" in e for e in errors)

        # 2. Field hilang / kosong
        _, errors2 = validate_kb({"relasi_tabel": [{"tabel": "untt_pembelian", "kolom": ""}]})
        assert len(errors2) > 0

        # 3. Identifier tidak sah (SQL injection attempt / karakter aneh)
        _, errors3 = validate_kb({
            "relasi_tabel": [{
                "tabel": "untt_pembelian; DROP TABLE users;",
                "kolom": "norangka",
                "merujuk_tabel": "untt_datakendaraan",
                "merujuk_kolom": "norangka",
            }]
        })
        assert any("bukan identifier yang valid" in e for e in errors3)

    def test_suntikkan_relasi_ke_skema(self):
        raw_schema = {
            "tables": {
                "untt_pembelian": {
                    "columns": [{"name": "nomor", "type": "varchar"}, {"name": "norangka", "type": "varchar"}],
                    "foreign_keys": []
                },
                "untt_datakendaraan": {
                    "columns": [{"name": "norangka", "type": "varchar"}, {"name": "kode_tipe", "type": "varchar"}],
                    "foreign_keys": []
                }
            }
        }
        relasi = [
            {
                "tabel": "untt_pembelian",
                "kolom": "norangka",
                "merujuk_tabel": "untt_datakendaraan",
                "merujuk_kolom": "norangka",
            }
        ]
        
        schema_baru = suntikkan_relasi_ke_skema(raw_schema, relasi)
        
        # Original schema harus tidak termutasi
        assert raw_schema["tables"]["untt_pembelian"]["foreign_keys"] == []
        
        # Schema baru harus memiliki foreign key virtual
        fks = schema_baru["tables"]["untt_pembelian"]["foreign_keys"]
        assert len(fks) == 1
        assert fks[0]["column"] == "norangka"
        assert fks[0]["references_table"] == "untt_datakendaraan"
        assert fks[0]["references_column"] == "norangka"

    def test_compose_sql_dengan_virtual_fk(self):
        # Database tanpa FK fisik (foreign_keys: [])
        raw_schema = {
            "tables": {
                "untt_pembelian": {
                    "columns": [{"name": "nomor", "type": "varchar"}, {"name": "norangka", "type": "varchar"}],
                    "foreign_keys": []
                },
                "untt_datakendaraan": {
                    "columns": [{"name": "norangka", "type": "varchar"}, {"name": "kode_tipe", "type": "varchar"}],
                    "foreign_keys": []
                }
            }
        }
        
        plan = {
            "tables": ["untt_pembelian", "untt_datakendaraan"],
            "columns": ["untt_pembelian.nomor", "untt_datakendaraan.kode_tipe"],
        }
        
        # 1. Tabel tanpa relasi dan tanpa shared key -> harus gagal
        schema_tanpa_relasi = {
            "tables": {
                "untt_pembelian": {
                    "columns": [{"name": "nomor", "type": "varchar"}],
                    "foreign_keys": []
                },
                "glbm_setting": {
                    "columns": [{"name": "config_val", "type": "varchar"}],
                    "foreign_keys": []
                }
            }
        }
        plan_gagal = {
            "tables": ["untt_pembelian", "glbm_setting"],
            "columns": ["untt_pembelian.nomor", "glbm_setting.config_val"],
        }
        with pytest.raises(SqlComposerError, match="tidak ada FK path"):
            compose_sql(plan_gagal, schema_tanpa_relasi)
            
        # 2. Dengan virtual FK -> berhasil menyusun JOIN deterministik
        relasi = [
            {
                "tabel": "untt_pembelian",
                "kolom": "norangka",
                "merujuk_tabel": "untt_datakendaraan",
                "merujuk_kolom": "norangka",
            }
        ]
        schema_dengan_fk = suntikkan_relasi_ke_skema(raw_schema, relasi)
        composed = compose_sql(plan, schema_dengan_fk)
        
        assert "JOIN \"untt_datakendaraan\" ON \"untt_datakendaraan\".\"norangka\" = \"untt_pembelian\".\"norangka\"" in composed["sql"]
        assert "SELECT \"untt_pembelian\".\"nomor\", \"untt_datakendaraan\".\"kode_tipe\" FROM \"untt_pembelian\"" in composed["sql"]

    @pytest.mark.anyio
    async def test_muat_kb_gabungan_relasi_tabel(self):
        from app.services.knowledge_base import muat_kb_gabungan
        
        class _StubPool:
            async def fetch(self, sql, *args):
                return []
                
        tenant_kb_raw = '{"relasi_tabel": [{"tabel": "untt_pembelian", "kolom": "norangka", "merujuk_tabel": "untt_datakendaraan", "merujuk_kolom": "norangka"}]}'
        merged = await muat_kb_gabungan(_StubPool(), tenant_kb_raw, schema_tables={"untt_pembelian", "untt_datakendaraan"})
        
        assert "relasi_tabel" in merged
        assert len(merged["relasi_tabel"]) == 1
        assert merged["relasi_tabel"][0]["tabel"] == "untt_pembelian"

