# 🤖 DMS AI Platform — AI-Powered Report & Database Management System

> Platform multi-tenant untuk mengelola database dan menghasilkan laporan berbasis AI. Admin dapat mengkonfigurasi koneksi database per cabang (branch), memilih AI provider (OpenAI / Anthropic), dan user cukup bertanya dalam bahasa natural untuk mendapatkan data.

---

## 📋 Daftar Isi

- [Arsitektur](#-arsitektur)
- [Tech Stack](#-tech-stack)
- [Prasyarat](#-prasyarat)
- [Instalasi & Setup](#-instalasi--setup)
- [Menjalankan Aplikasi](#-menjalankan-aplikasi)
- [Struktur Project](#-struktur-project)
- [Database Schema](#-database-schema)
- [API Endpoints](#-api-endpoints)
- [Akun Default](#-akun-default)
- [Environment Variables](#-environment-variables)

---

## 🏗 Arsitektur

```
┌─────────────────┐       ┌─────────────────────┐       ┌──────────────────┐
│   React + Vite  │──────▶│  FastAPI (Backend)   │──────▶│  PostgreSQL 15   │
│   (Frontend)    │  API  │  - Auth (JWT)        │  Core │  (Core Database) │
│   Port: 5173    │       │  - Admin CRUD        │  DB   │  Port: 5433      │
└─────────────────┘       │  - AI Orchestrator   │       └──────────────────┘
                          │  Port: 8000          │
                          └──────────┬───────────┘       ┌──────────────────┐
                                     │                   │  Redis 7         │
                                     ├──────────────────▶│  (Session/Cache) │
                                     │  Cache            │  Port: 6379      │
                                     │                   └──────────────────┘
                                     │
                                     │  AI Request       ┌──────────────────┐
                                     └──────────────────▶│  AI Provider     │
                                                         │  (OpenAI/Claude) │
                                                         └──────────────────┘
```

Sistem ini menggunakan arsitektur **multi-tenant**. Setiap cabang (branch) dapat terhubung ke database terpisah (tenant) sehingga data antar cabang terisolasi.

---

## 🛠 Tech Stack

### Backend
| Teknologi | Versi | Kegunaan |
|---|---|---|
| **Python** | 3.10+ | Bahasa pemrograman utama |
| **FastAPI** | 0.115 | Web framework (async) |
| **Uvicorn** | 0.34 | ASGI server |
| **asyncpg** | 0.30 | PostgreSQL async driver |
| **Pydantic** | 2.10 | Data validation & serialization |
| **python-jose** | 3.4 | JWT token handling |
| **passlib + bcrypt** | — | Password hashing |
| **cryptography (Fernet)** | 44.0 | Enkripsi kredensial tenant & API key |
| **sqlglot** | 26.3 | SQL parsing & validation |
| **Redis** | 5.2 | Caching & session store |

### Frontend
| Teknologi | Versi | Kegunaan |
|---|---|---|
| **React** | 19.x | UI library |
| **Vite** | 8.x | Build tool & dev server |
| **Tailwind CSS** | 4.x | Utility-first CSS framework |
| **Axios** | 1.19 | HTTP client |
| **Framer Motion** | 13.x | Animasi & transisi |
| **Recharts** | 3.x | Grafik & visualisasi data |
| **Lucide React** | 1.33 | Icon library |
| **React Hot Toast** | 2.6 | Notifikasi toast |

### Infrastructure
| Teknologi | Versi | Kegunaan |
|---|---|---|
| **Docker Compose** | 3.8 | Container orchestration |
| **PostgreSQL** | 15 | Database utama (core) |
| **Redis** | 7 | Session & cache layer |

---

## 📦 Prasyarat

Pastikan sudah terinstall di komputer Anda:

- [Python](https://www.python.org/) ≥ 3.10
- [Node.js](https://nodejs.org/) ≥ 18 (disarankan LTS)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (untuk PostgreSQL & Redis)
- [Git](https://git-scm.com/)

---

## 🚀 Instalasi & Setup

### 1. Clone Repository

```bash
git clone https://github.com/kamachiii/AI-Reporting.git
cd AI-Reporting
```

### 2. Jalankan Database & Redis (Docker)

```bash
docker-compose up -d
```

Ini akan menjalankan:
- **PostgreSQL 15** di port `5433` (database: `ai-dms`)
- **Redis 7** di port `6379`

### 3. Setup Backend

```bash
cd backend

# Buat virtual environment
python -m venv .venv

# Aktivasi (Windows)
.venv\Scripts\activate

# Aktivasi (macOS/Linux)
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Konfigurasi Environment

Buat file `backend/.env` (atau sesuaikan yang sudah ada):

```env
CORE_DB_HOST=localhost
CORE_DB_PORT=5433
CORE_DB_NAME=ai-dms
CORE_DB_USER=postgres
CORE_DB_PASSWORD=postgres

REDIS_URL=redis://localhost:6379/0

JWT_SECRET_KEY=super_secure_random_key_32_char_min

FERNET_KEY=<generate_dengan_python>
```

> **Tip:** Generate `FERNET_KEY` dengan menjalankan:
> ```python
> from cryptography.fernet import Fernet
> print(Fernet.generate_key().decode())
> ```

### 5. Inisialisasi Database

```bash
cd backend
python init_db.py
```

Script ini akan:
- Membuat semua tabel dari `sql/2_DATABASE_DDL.sql`
- Membuat data awal (company, branch, user admin & user biasa)

### 6. Setup Frontend

```bash
cd frontend
npm install
```

---

## ▶ Menjalankan Aplikasi

### Backend (Terminal 1)

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Backend tersedia di: **http://localhost:8000**
Dokumentasi API (Swagger): **http://localhost:8000/docs**

### Frontend (Terminal 2)

```bash
cd frontend
npm run dev
```

Frontend tersedia di: **http://localhost:5173**

---

## 📁 Struktur Project

```
ai-report-database-mandiri/
├── docker-compose.yml          # PostgreSQL + Redis containers
├── Readme.md
│
├── backend/
│   ├── .env                    # Environment variables
│   ├── requirements.txt        # Python dependencies
│   ├── init_db.py              # Database initialization & seeding
│   ├── sql/
│   │   └── 2_DATABASE_DDL.sql  # Database schema (DDL)
│   └── app/
│       ├── main.py             # FastAPI entry point
│       ├── core/
│       │   ├── config.py       # Application settings (Pydantic)
│       │   ├── database.py     # PostgreSQL pool & Redis connection
│       │   └── security.py     # JWT, bcrypt, Fernet encryption
│       ├── routers/
│       │   ├── auth.py         # Login endpoint
│       │   └── admin.py        # Admin CRUD (company, branch, tenant, AI config)
│       └── services/
│           └── ai_orchestrator.py  # AI provider integration (OpenAI/Anthropic)
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx             # Root component (routing by role)
        ├── App.css
        ├── index.css
        ├── services/
        │   └── api.js          # Axios API client
        └── components/
            ├── LoginModal.jsx  # Halaman login
            └── Admin/
                ├── AdminLayout.jsx       # Layout admin (sidebar + tabs)
                ├── CompanyBranchesTab.jsx # Manajemen company & branch
                ├── TenantsTab.jsx        # Manajemen tenant database
                ├── AIConfigTab.jsx       # Konfigurasi AI provider
                ├── ModelPickerModal.jsx  # Modal pemilihan model AI
                ├── AuditLogTab.jsx       # Log audit query
                └── UsersTab.jsx          # Manajemen user
```

---

## 🗄 Database Schema

Platform ini menggunakan **9 tabel** di database core (`ai-dms`):

```mermaid
erDiagram
    companies ||--o{ branches : "has"
    branches ||--o| tenants : "connects to"
    branches ||--o{ user_branches : "assigned via"
    users ||--o{ user_branches : "belongs to"
    users ||--o{ conversations : "creates"
    users ||--o{ audit_logs : "triggers"
    conversations ||--o{ messages : "contains"

    companies {
        serial id PK
        varchar code UK
        varchar name
        text address
        boolean is_active
    }

    users {
        serial id PK
        varchar username UK
        varchar password_hash
        varchar email
        varchar role "admin | user"
    }

    branches {
        serial id PK
        varchar code UK
        varchar name
        varchar company_code FK
        boolean is_active
    }

    tenants {
        serial id PK
        varchar branch_code FK_UK
        varchar db_host
        integer db_port
        varchar db_name
        varchar db_username
        text db_password "encrypted"
        jsonb schema_config_json
        integer daily_token_quota
    }

    ai_configs {
        serial id PK
        varchar scope "global | branch"
        varchar target_id
        varchar provider
        varchar model
        text api_key "encrypted"
        float temperature
        varchar api_type "openai | anthropic"
        varchar base_url
    }

    audit_logs {
        serial id PK
        integer user_id FK
        varchar branch_code
        text prompt_text
        jsonb ai_json_filter
        text generated_sql
        integer execution_time_ms
        varchar status
    }

    conversations {
        serial id PK
        integer user_id FK
        varchar branch_code
        varchar title
        jsonb summary_json
    }

    messages {
        serial id PK
        integer conversation_id FK
        varchar role
        text content
        integer token_count
    }
```

---

## 🔌 API Endpoints

### Authentication
| Method | Endpoint | Deskripsi |
|---|---|---|
| `POST` | `/auth/login` | Login dengan username & password |

### Admin — Company
| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/admin/companies` | Daftar semua company |
| `POST` | `/admin/companies` | Buat company baru |
| `PUT` | `/admin/companies/{code}` | Update company |
| `DELETE` | `/admin/companies/{code}` | Hapus company |

### Admin — Branch
| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/admin/branches` | Daftar semua branch |
| `POST` | `/admin/branches` | Buat branch baru |
| `PUT` | `/admin/branches/{code}` | Update branch |
| `DELETE` | `/admin/branches/{code}` | Hapus branch |

### Admin — Tenant (Database Connection)
| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/admin/tenants` | Daftar semua tenant |
| `GET` | `/admin/tenants/{branch_code}` | Detail tenant per branch |
| `GET` | `/admin/branches-with-tenants` | Branch dengan status tenant |
| `POST` | `/admin/tenants` | Buat koneksi tenant baru |
| `POST` | `/admin/tenants/{branch_code}/test-connection` | Test koneksi tenant |
| `POST` | `/admin/tenants/test-draft` | Test draft koneksi (sebelum save) |

### Admin — AI Configuration
| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/admin/ai-configs` | Daftar semua AI config |
| `POST` | `/admin/ai-configs` | Buat AI config baru |
| `PUT` | `/admin/ai-configs/{id}` | Update AI config |
| `DELETE` | `/admin/ai-configs/{id}` | Hapus AI config |
| `POST` | `/admin/ai-configs/{id}/test` | Test AI config |
| `POST` | `/admin/ai-configs/test-draft` | Test draft config |
| `POST` | `/admin/ai-providers/models` | Fetch daftar model dari provider |

> 📖 Dokumentasi API lengkap tersedia di **http://localhost:8000/docs** (Swagger UI)

---

## 👤 Akun Default

Setelah menjalankan `init_db.py`, akun berikut tersedia:

| Username | Password | Role | Branch |
|---|---|---|---|
| `admin` | `admin123` | Admin | JKT_01, SBY_02 |
| `user_jkt` | `user123` | User | JKT_01 |

> ⚠️ **Penting:** Ganti password default sebelum deploy ke production!

---

## ⚙ Environment Variables

| Variable | Deskripsi | Default |
|---|---|---|
| `CORE_DB_HOST` | Host PostgreSQL | `localhost` |
| `CORE_DB_PORT` | Port PostgreSQL | `5433` |
| `CORE_DB_NAME` | Nama database core | `ai-dms` |
| `CORE_DB_USER` | Username PostgreSQL | `postgres` |
| `CORE_DB_PASSWORD` | Password PostgreSQL | `postgres` |
| `REDIS_URL` | URL koneksi Redis | `redis://localhost:6379/0` |
| `JWT_SECRET_KEY` | Secret key untuk JWT token | — |
| `FERNET_KEY` | Key untuk enkripsi kredensial | — |

---

## 🔒 Keamanan

- **JWT Authentication** — Token berbasis HS256 dengan masa berlaku 24 jam
- **Bcrypt Password Hashing** — Password di-hash menggunakan bcrypt
- **Fernet Encryption** — Kredensial database tenant dan API key AI dienkripsi saat disimpan
- **Role-Based Access Control** — Endpoint admin dilindungi dengan middleware `require_admin_role`
- **CORS** — Hanya origin tertentu yang diizinkan (localhost dev server)

---

## 📄 Lisensi

Project ini dibuat sebagai bagian dari program **PKL (Praktik Kerja Lapangan)**.

---

<p align="center">
  Dibuat dengan menggunakan FastAPI + React
</p>
