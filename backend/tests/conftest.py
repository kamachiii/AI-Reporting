"""
Konfigurasi pytest untuk backend.

Menjalankan test yang tidak butuh database:
    cd backend && .venv/Scripts/python -m pytest tests/ -v

Test yang butuh DB (integration) diberi marker @pytest.mark.integration
dan hanya jalan jika Docker Postgres hidup.
"""
import os
import sys

# Pastikan package app bisa diimport dari root backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
