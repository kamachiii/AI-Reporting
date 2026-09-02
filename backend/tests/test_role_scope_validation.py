"""
Test validasi murni (tanpa DB) untuk kebijakan role & scope:

1. users: role admin TIDAK boleh punya branch_codes (keputusan domain 2026-08-31:
   admin = pengatur sistem FBS, tanpa penugasan cabang, tanpa akses chat).
2. ai_configs: scope wajib punya target_id valid sesuai jenisnya (tenant/user).
"""
import asyncio
import pytest
from fastapi import HTTPException

from app.routers.admin.users import _validate_role_and_branches
from app.routers.admin.ai_configs import validate_scope_target_shape


class TestAdminNoBranches:
    """Keputusan domain: admin tanpa cabang — selalu."""

    def test_admin_with_branches_rejected(self):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_validate_role_and_branches(pool=None, role="admin", branch_codes=["JKT_01"]))
        assert exc.value.status_code == 400
        assert "Admin" in exc.value.detail

    def test_admin_with_empty_branches_ok(self):
        # tidak raise = lolos (pool tak disentuh karena branch_codes kosong)
        asyncio.run(_validate_role_and_branches(pool=None, role="admin", branch_codes=[]))

    def test_user_branches_ok(self):
        # role user boleh punya cabang — pool disentuh; mock pool minimal
        class FakePool:
            async def fetch(self, *_a, **_k):
                return [{"code": "JKT_01"}]
        asyncio.run(_validate_role_and_branches(FakePool(), role="user", branch_codes=["JKT_01"]))


class TestScopeTargetShape:
    """target_id wajib ada utk scope tenant/user; kosong dilarang; format diperiksa ringan."""

    def test_global_ignores_target(self):
        validate_scope_target_shape("global", "")

    def test_tenant_empty_rejected(self):
        with pytest.raises(HTTPException) as exc:
            validate_scope_target_shape("tenant", "")
        assert exc.value.status_code == 400

    def test_user_empty_rejected(self):
        with pytest.raises(HTTPException) as exc:
            validate_scope_target_shape("user", "")
        assert exc.value.status_code == 400

    def test_target_with_space_rejected(self):
        with pytest.raises(HTTPException):
            validate_scope_target_shape("tenant", "JKT 01")

    def test_target_too_long_rejected(self):
        with pytest.raises(HTTPException):
            validate_scope_target_shape("user", "x" * 101)

    def test_valid_target_ok(self):
        validate_scope_target_shape("tenant", "JKT_01")
        validate_scope_target_shape("user", "tester01")


class TestUpdateBranchWithoutRole:
    """Regresi bug live 2026-09-02: PUT /admin/users/{id} dgn branch_codes saja
    (tanpa role) -> NameError current_role -> 500. Harus 200."""

    def test_current_role_always_fetched(self):
        # Verifikasi statis: current_role di-assign SEBELUM blok demote, di luar if.
        import re
        src = open(r"D:/Kerja PKL/ai-report-database-mandiri/backend/app/routers/admin/users.py",
                   encoding="utf-8").read()
        m = re.search(r"current_role = await conn\.fetchval", src)
        assert m, "current_role assignment hilang"
        line_start = src[:m.start()].rfind("\n")
        indent = src[line_start+1:line_start+1+16]
        # assignment harus di level body transaksi (16 spasi), bukan di dalam if demote (20 spasi)
        assert indent.startswith(" " * 16) and not indent.startswith(" " * 20), \
            f"current_role di-indent {len(indent)-indent.count(' ')} level — harus level transaksi"
