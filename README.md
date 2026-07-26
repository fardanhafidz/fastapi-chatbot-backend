# FastAPI AI Chatbot Backend

Backend layanan chatbot kecerdasan buatan serbaguna (general-purpose) berbasis FastAPI dan OpenAI Responses API terbaru. Proyek ini dirancang sebagai templat arsitektur yang dapat disesuaikan untuk berbagai kebutuhan spesifik (customer service, asisten virtual perusahaan, institusi pendidikan, maupun aplikasi bisnis lainnya) secara responsif, aman, dan efisien.

---

## Fitur Utama

- **OpenAI Responses API**: Menggunakan arsitektur terbaru (`client.responses.create`) yang mendukung kesinambungan sesi percakapan (stateful).
- **Kustomisasi Fleksibel**: Kepribadian, identitas, batas pengetahuan, dan instruksi sistem bot dapat dikonfigurasi dengan mudah tanpa mengubah kode sumber hanya melalui berkas `.env`.
- **Keamanan Ganda**: Dilengkapi validasi header otentikasi internal (`X-API-Key`) dan konfigurasi CORS yang aman untuk lingkungan produksi.
- **Proteksi Rate Limiting**: Memitigasi serangan spam dan penyalahgunaan kuota token menggunakan middleware SlowAPI (pembatasan request per menit).
- **Frontend Testing UI**: Menyediakan halaman pengujian antarmuka obrolan satu halaman (one-page HTML) yang dapat diakses langsung melalui server backend.
- **Dokumentasi API Otomatis**: Dukungan penuh untuk Swagger UI dan ReDoc untuk kemudahan integrasi aplikasi antarmuka.

---

## Struktur Proyek

```text
fastapi-chatbot-backend/
├── app/
│   ├── __init__.py
│   ├── main.py          # Entry point FastAPI, CORS middleware, dan proteksi rute
│   ├── config.py        # Manajemen environment variables (Pydantic Settings)
│   ├── services.py      # Logika panggilan asinkron ke OpenAI SDK
│   └── schemas.py       # Validasi struktur data request dan response
├── frontend/
│   └── index.html       # Antarmuka pengujian chatbot (Floating UI Widget)
├── .env.example         # Templat variabel lingkungan untuk konfigurasi lokal
├── .gitignore           # Daftar berkas yang diabaikan oleh Git
├── Procfile             # Instruksi deployment cloud (Render, Railway, Heroku)
├── requirements.txt     # Daftar dependensi library Python
└── README.md            # Dokumentasi proyek
```

---

## Persyaratan Sistem

- Python 3.10 atau versi yang lebih baru
- Git
- Kunci API OpenAI (OpenAI API Key) yang aktif

---

## Instalasi dan Konfigurasi Lokal

1. **Klona Repositori dan Masuk ke Direktori Proyek**
   ```bash
   git clone https://github.com/fardanhafidz/fastapi-chatbot-backend
   cd fastapi-chatbot-backend
   ```

2. **Buat dan Aktifkan Virtual Environment**
   - Pada Windows (PowerShell):
     ```powershell
     python -m venv venv
     .\venv\Scripts\activate
     ```
   - Pada Linux/macOS:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. **Install Dependensi Library**
   ```bash
   pip install -r requirements.txt
   ```

4. **Konfigurasi Environment Variables**
   Salin berkas templat lingkungan menjadi berkas `.env` lokal:
   - Pada Windows (PowerShell):
     ```powershell
     copy .env.example .env
     ```
   - Pada Linux/macOS:
     ```bash
     cp .env.example .env
     ```

   Buka berkas `.env` di editor teks Anda dan sesuaikan nilai parameter berikut:
   ```ini
   APP_NAME="FastAPI AI Chatbot"
   APP_ENV="development"
   PORT=8000
   ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:8000"

   # Kunci keamanan internal untuk mengakses endpoint API
   INTERNAL_API_KEY="secret-internal-api-key-2026"

   # Kunci dan konfigurasi OpenAI
   OPENAI_API_KEY="sk-xxxx-api-key-openai-anda"
   OPENAI_MODEL="gpt-5.5"
   OPENAI_SYSTEM_INSTRUCTIONS="Kamu adalah Asisten AI yang ramah, profesional, dan informatif. Tugasmu adalah membantu menjawab pertanyaan pengguna dengan jelas dan akurat."
   ```

---

## Cara Menjalankan Server

Pastikan virtual environment telah aktif, lalu jalankan perintah berikut:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Server akan aktif pada alamat: `http://127.0.0.1:8000`

---

## Cara Pengujian

### 1. Pengujian Antarmuka Obrolan (Frontend Demo)
Buka web browser dan akses URL berikut untuk mencoba widget obrolan secara langsung:
- URL: `http://127.0.0.1:8000/demo` (atau `http://127.0.0.1:8000/chat`)

### 2. Pengujian via Dokumentasi Swagger UI
Akses halaman dokumentasi interaktif pada browser:
- URL: `http://127.0.0.1:8000/docs`
- Klik tombol **Authorize** di sudut kanan atas.
- Masukkan nilai `INTERNAL_API_KEY` (contoh: `secret-internal-api-key-2026`).
- Klik **Authorize**, lalu **Close**. Anda kini dapat menguji endpoint `/api/v1/chat` dan `/api/v1/conversations` secara langsung dari Swagger.

### 3. Pengujian via cURL (Terminal / Command Prompt)
Contoh pengiriman pesan ke obrolan menggunakan cURL:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
     -H "Content-Type: application/json" \
     -H "X-API-Key: secret-internal-api-key-2026" \
     -d '{"message": "Halo, bisakah Anda membantu menjelaskan layanan yang tersedia?"}'
```

---

## Daftar Endpoint API

| Metode | Rute | Deskripsi | Batas Laju (Rate Limit) | Auth Wajib |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/` | Pemeriksaan kesehatan sistem (Health Check) | - | Tidak |
| `GET` | `/demo` | Antarmuka pengujian frontend chatbot | - | Tidak |
| `POST` | `/api/v1/conversations` | Inisialisasi ID sesi percakapan baru | 15 / menit | Ya (`X-API-Key`) |
| `POST` | `/api/v1/chat` | Mengirim pesan ke AI dan menerima jawaban obrolan | 20 / menit | Ya (`X-API-Key`) |

---

## Panduan Deployment ke Produksi (Cloud Hosting)

Proyek ini telah dilengkapi dengan berkas `Procfile` sehingga kompatibel untuk langsung di-deploy ke platform cloud seperti Render, Railway, Heroku, atau Fly.io.

Perhatikan poin berikut sebelum melakukan deployment produksi:
1. Atur variabel lingkungan (Environment Variables) pada dasbor cloud provider Anda dengan nilai dari `.env`.
2. Ubah `APP_ENV` menjadi `production` dan `DEBUG` menjadi `False`.
3. Sesuaikan parameter `ALLOWED_ORIGINS` hanya dengan nama domain resmi situs web antarmuka Anda, jangan gunakan wildcard (`*`) atau localhost.
4. Pastikan `INTERNAL_API_KEY` dikonfigurasi dengan kombinasi karakter acak yang kuat agar endpoint API terlindungi dengan maksimal.
