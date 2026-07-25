# Audit & Revisi Kode Backend Chatbot (FastAPI + OpenAI)

Dokumen ini berisi hasil tinjauan (code review), analisis kerentanan keamanan, temuan bug, serta rekomendasi perbaikan lengkap untuk proyek **FastAPI OpenAI Chatbot Backend**.

---

## 1. Ringkasan Eksekutif (Executive Summary)

Secara struktur umum, proyek ini sudah terorganisasi dengan baik menggunakan pola arsitektur modular (pemisahan antara `config`, `schemas`, `services`, dan `main`). Penggunaan `pydantic-settings` dan SDK resmi `openai` (v2) dengan metode asinkron (`AsyncOpenAI`) juga merupakan langkah yang tepat.

Namun, dalam audit mendalam ditemukan beberapa **kerentanan keamanan berisiko tinggi**, **bug logika pada saat runtime**, dan **kekurangan dalam pembatasan beban kerja (rate limiting/input validation)** yang dapat menyebabkan kerugian finansial (tagihan OpenAI membengkak) atau gangguan layanan (*Denial of Service*).

---

## 2. Temuan Kritis & Kerentanan Keamanan (Security Vulnerabilities)

### 🚨 [KRITIS] 1. Potensi Kebocoran CORS & Konflik Wildcard (`allow_credentials=True`)
- **Lokasi**: `app/main.py` (Baris 27-33) & `app/config.py` (Baris 31-36)
- **Masalah**: 
  Pada konfigurasi CORS middleware, parameter `allow_credentials=True` diatur bersamaan dengan `allow_origins=settings.allowed_origins`. Jika dalam file `.env` variabel `ALLOWED_ORIGINS` dikosongkan, fungsi `allowed_origins` di `config.py` akan mengembalikan `["*"]` (wildcard).
  Berdasarkan spesifikasi keamanan browser modern (W3C Fetch/CORS), penggunaan origin wildcard `*` **dilarang keras** jika `allow_credentials=True` (cookie / token otorisasi diaktifkan). Hal ini akan menyebabkan browser memblokir seluruh request dari frontend.
- **Dampak**: Aplikasi gagal diakses oleh frontend, atau jika keliru dikonfigurasi di lingkungan produksi, berisiko membuka celah serangan *Cross-Site Request Forgery* (CSRF).
- **Koreksi**: 
  - Ubah logika di `config.py` agar tidak mengembalikan `["*"]` jika aplikasi berjalan di lingkungan produksi.
  - Jika memang membutuhkan wildcard `*` untuk tujuan pengembangan lokal, maka set `allow_credentials=False` atau lakukan validasi secara eksplisit.

---

### 🚨 [TINGGI] 2. Ketiadaan Pembatasan Request (Rate Limiting / Denial of Wallet)
- **Lokasi**: `app/main.py` (Endpoint `/api/v1/chat` dan `/api/v1/threads`)
- **Masalah**: 
  Tidak ada mekanisme pembatasan jumlah request (rate limiting) dari sisi backend (misalnya menggunakan library `slowapi`).
- **Dampak**: 
  Penyerang atau bot dapat melakukan spam/flood request ke endpoint `/api/v1/chat`. Karena setiap request memanggil API berbayar OpenAI, hal ini dapat menguras kuota saldo tagihan akun OpenAI pemilik server dalam waktu singkat (*Denial of Wallet* / *Billing Exhaustion Attack*) serta memicu status `429 Too Many Requests` dari OpenAI yang melumpuhkan layanan bagi pengguna sah.
- **Koreksi**: 
  Implementasikan Rate Limiting di level endpoint (contoh: maksimal 10-20 request per menit per IP address).

---

### 🚨 [TINGGI] 3. Endpoint Publik Tanpa Otentikasi (Missing Authentication/Authorization)
- **Lokasi**: `app/main.py` (Semua endpoint di bawah `/api/v1/`)
- **Masalah**: 
  Endpoint percakapan terbuka secara publik tanpa pemeriksaan otorisasi (seperti API Key internal, Bearer Token / JWT, atau pengecekan sesi).
- **Dampak**: 
  Siapapun yang mengetahui URL server backend ini dapat memanfaatkan model AI secara gratis menggunakan biaya pemilik server.
- **Koreksi**: 
  Add middleware atau dependency injection untuk memvalidasi header otentikasi (misalnya `X-API-Key` atau `Authorization: Bearer <token>`) dari klien/frontend yang bersangkutan.

---

### ⚠️ [SEDANG] 4. Ketiadaan Batas Maksimal Karakter pada Pesan (Payload Bloat)
- **Lokasi**: `app/schemas.py` (`ChatRequest.message`)
- **Masalah**: 
  Field `message` hanya dibatasi `min_length=1`, tanpa batas maksimal (`max_length`).
- **Dampak**: 
  Pengguna dapat mengirimkan teks berukuran sangat besar (misal 1 Megabyte / ratusan ribu karakter) dalam satu request. Ini dapat memicu error dari batas *context window* OpenAI atau menghabiskan saldo token secara berlebihan.
- **Koreksi**: 
  Tambahkan `max_length=4000` (atau batas wajar lain yang sesuai untuk chatbot).

---

## 3. Bug & Kesalahan Logika (Bugs & Runtime Errors)

### 🐞 [TINGGI] 5. Inisialisasi Klien Asinkron pada Singleton di Luar Event Loop
- **Lokasi**: `app/services.py` (Baris 15 & 123)
- **Masalah**: 
  `self.client = AsyncOpenAI(...)` diinstansiasi langsung saat modul diimpor (`openai_service = OpenAIService()`). Dalam ekosistem asinkron Python (FastAPI/Uvicorn), membuat klien HTTP asinkron di luar *event loop* aktif dapat memicu error `RuntimeError: Event loop is closed` saat server di-reload, dijalankan dengan multi-workers (`uvicorn --workers N`), atau saat pengujian (unit testing).
- **Koreksi**: 
  Inisialisasi klien di dalam *event loop* aktif menggunakan pola **FastAPI Lifespan** (pada `main.py`) atau gunakan *Dependency Injection* (`Depends`) yang menyediakan klien saat request terjadi.

---

### 🐞 [SEDANG] 6. Bug Logika Fallback Pengambilan Pesan Assistant yang Menyesatkan
- **Lokasi**: `app/services.py` (Baris 101-109)
- **Masalah**: 
  Jika sistem gagal menemukan balasan assistant yang cocok dengan `run_id` saat ini, terdapat logika *fallback* yang mengambil pesan assistant **terbaru apapun** dari thread tersebut:
  ```python
  if not response_text.strip():
      for msg in messages.data:
          if msg.role == "assistant":
              ...
              break
  ```
- **Dampak**: 
  Jika eksekusi run saat ini mengalami kegagalan internal atau tidak menghasilkan teks (misal karena *function calling* atau content filter), sistem justru akan mengambil **jawaban dari pertanyaan sebelumnya** dan menampilkannya sebagai jawaban seolah-olah untuk pertanyaan baru. Ini sangat menyesatkan pengguna.
- **Koreksi**: 
  Hapus logika fallback tersebut. Jika `run_id` saat ini tidak mengembalikan pesan teks dari assistant, lemparkan exception yang jelas bahwa AI tidak menghasilkan jawaban teks.

---

### 🐞 [SEDANG] 7. Penanganan Error HTTP yang Kurang Tepat untuk Exception OpenAI
- **Lokasi**: `app/main.py` (Baris 117-122)
- **Masalah**: 
  Saat ini semua error dari OpenAI di luar Autentikasi dan Rate Limit ditangkap oleh blok umum `OpenAIError` dan dikembalikan sebagai HTTP `502 Bad Gateway`.
  Jika klien/frontend mengirimkan `thread_id` yang salah atau sudah dihapus, SDK OpenAI akan melempar `NotFoundError` (HTTP 404). Jika format request tidak valid, SDK melempar `BadRequestError` (HTTP 400).
- **Dampak**: 
  Frontend menerima status HTTP `502` padahal kesalahan ada pada input pengguna (misal thread tidak ditemukan), sehingga menyulitkan *error handling* di sisi frontend.
- **Koreksi**: 
  Tangkap secara spesifik `NotFoundError` (kembalikan HTTP 404) dan `BadRequestError` (kembalikan HTTP 400) sebelum blok `OpenAIError`.

---

## 4. Perbaikan Struktur Kode & Praktik Terbaik

### 💡 8. Validasi Format ID Menggunakan Regex
- **Lokasi**: `app/schemas.py`
- ID Thread OpenAI selalu diawali dengan prefix `thread_` dan Assistant ID diawali dengan `asst_`.
- **Saran**: Tambahkan validasi regex (`pattern=r"^thread_[a-zA-Z0-9]+$"`) pada Pydantic agar masukan yang jelas salah format langsung ditolak dengan HTTP 422 tanpa perlu membuang waktu memanggil API OpenAI.

### 💡 9. Polling Blokir vs Streaming (Saran Jangka Panjang)
- **Lokasi**: `app/services.py` (Baris 72: `create_and_poll`)
- Metode `create_and_poll` akan memblokir request HTTP hingga model selesai berpikir. Untuk jawaban yang panjang, request HTTP bisa mengalami *timeout* dari pihak Gateway/Reverse Proxy (Nginx / Cloudflare biasanya memiliki batas timeout 30-60 detik).
- **Saran**: Untuk pengembangan selanjutnya, pertimbangkan menggunakan **Streaming Response** (Server-Sent Events / SSE) menggunakan `AsyncAssistantEventHandler` agar pengguna langsung melihat teks bertahap dan menghindari risiko HTTP timeout.

---

## 5. Panduan & Implementasi Kode Perbaikan (Revising The Code)

Berikut adalah contoh perbaikan kode konkret untuk file-file utama:

### A. Perbaikan `app/schemas.py` (Validasi Input & Batas Karakter)
```python
from typing import Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(
        ..., 
        min_length=1, 
        max_length=4000, 
        description="Pesan dari pengguna (maksimal 4000 karakter)"
    )
    thread_id: Optional[str] = Field(
        None, 
        pattern=r"^thread_[a-zA-Z0-9]+$", 
        description="ID Thread OpenAI yang valid (diawali 'thread_')"
    )
    assistant_id: Optional[str] = Field(
        None, 
        pattern=r"^asst_[a-zA-Z0-9]+$", 
        description="Override Assistant ID (diawali 'asst_')"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Halo, apa yang bisa kamu bantu hari ini?",
                "thread_id": "thread_abc123"
            }
        }
    }

# ... (kelas schema lainnya tetap sama)
```

---

### B. Perbaikan `app/services.py` (Menghapus Fallback Menyesatkan & Aman dari Event Loop)
```python
import logging
from typing import Tuple, Optional
from openai import AsyncOpenAI, OpenAIError, RateLimitError, AuthenticationError, NotFoundError, BadRequestError
from app.config import settings

logger = logging.getLogger("api.services")

class OpenAIService:
    def __init__(self, client: Optional[AsyncOpenAI] = None):
        # Inisialisasi client secara dinamis atau via dependency injection
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)
        self.default_assistant_id = settings.openai_assistant_id

    async def create_thread(self) -> str:
        try:
            thread = await self.client.beta.threads.create()
            logger.info(f"Berhasil membuat thread baru: {thread.id}")
            return thread.id
        except Exception as e:
            logger.error(f"Error saat membuat thread OpenAI: {str(e)}")
            raise e

    async def chat_with_assistant(
        self, 
        message: str, 
        thread_id: Optional[str] = None, 
        assistant_id: Optional[str] = None
    ) -> Tuple[str, str, str, str]:
        target_assistant_id = assistant_id or self.default_assistant_id
        if not target_assistant_id or target_assistant_id == "asst_your_assistant_id_here":
            raise ValueError("OPENAI_ASSISTANT_ID belum dikonfigurasi dengan benar di file .env atau request.")

        if not thread_id:
            thread_id = await self.create_thread()

        # Tambahkan pesan baru
        await self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message
        )

        # Jalankan dan tunggu hasil run
        run = await self.client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=target_assistant_id,
            poll_interval_ms=1000
        )

        if run.status != "completed":
            error_detail = f"Run tidak selesai (Status: {run.status})."
            if hasattr(run, "last_error") and run.last_error:
                error_detail += f" Detail: {run.last_error}"
            logger.error(error_detail)
            raise RuntimeError(error_detail)

        # Ambil riwayat pesan
        messages = await self.client.beta.threads.messages.list(
            thread_id=thread_id,
            order="desc",
            limit=10
        )

        response_text = ""
        for msg in messages.data:
            # PENTING: Hanya ambil pesan dari run_id saat ini agar tidak salah mengambil pesan lama!
            if msg.role == "assistant" and msg.run_id == run.id:
                for content_block in msg.content:
                    if content_block.type == "text":
                        response_text += content_block.text.value + "\n"
                break

        if not response_text.strip():
            raise RuntimeError("Assistant selesai memproses, namun tidak menghasilkan jawaban teks.")

        return response_text.strip(), thread_id, run.id, run.status

# Dependency provider untuk diinjeksi ke endpoint FastAPI
def get_openai_service() -> OpenAIService:
    return OpenAIService()
```

---

### C. Perbaikan `app/main.py` (Penanganan Error Semantik, CORS & Dependency Injection)
```python
import logging
from fastapi import FastAPI, HTTPException, status, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from openai import AuthenticationError, RateLimitError, OpenAIError, NotFoundError, BadRequestError

from app.config import settings
from app.schemas import ChatRequest, ChatResponse, ThreadCreateResponse, HealthResponse
from app.services import OpenAIService, get_openai_service

logger = logging.getLogger("api.main")

app = FastAPI(
    title=settings.app_name,
    description="Backend API untuk Chatbot AI berbasis FastAPI dan OpenAI Assistants API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Keamanan: Contoh proteksi sederhana menggunakan API Key internal (Opsional/Sangat Disarankan)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    # Untuk produksi, bandingkan dengan secret key di .env
    # if api_key != settings.internal_api_key:
    #     raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    pass

# Konfigurasi CORS Middleware yang Aman
# Hindari wildcard '*' jika allow_credentials=True
allowed_origins = settings.allowed_origins
if "*" in allowed_origins and settings.app_env == "production":
    logger.warning("Peringatan Keamanan: Wildcard CORS terdeteksi di lingkungan produksi!")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True if "*" not in allowed_origins else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_model=HealthResponse, tags=["Health"])
async def health_check():
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.app_env,
        version="1.0.0"
    )

@app.post("/api/v1/threads", response_model=ThreadCreateResponse, status_code=status.HTTP_201_CREATED, tags=["Threads"])
async def create_new_thread(service: OpenAIService = Depends(get_openai_service)):
    try:
        thread_id = await service.create_thread()
        return ThreadCreateResponse(
            thread_id=thread_id,
            message="Thread percakapan berhasil dibuat"
        )
    except AuthenticationError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autentikasi ke OpenAI gagal.")
    except OpenAIError as e:
        logger.error(f"Gagal membuat thread: {str(e)}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Kesalahan dari OpenAI: {str(e)}")
    except Exception as e:
        logger.error(f"Internal server error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Terjadi kesalahan internal.")

@app.post("/api/v1/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK, tags=["Chat"])
async def chat_endpoint(
    request: ChatRequest, 
    service: OpenAIService = Depends(get_openai_service)
):
    try:
        response_text, thread_id, run_id, run_status = await service.chat_with_assistant(
            message=request.message,
            thread_id=request.thread_id,
            assistant_id=request.assistant_id
        )
        return ChatResponse(
            response=response_text,
            thread_id=thread_id,
            run_id=run_id,
            status=run_status
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except NotFoundError as e:
        # Menangani thread_id atau assistant_id yang tidak ditemukan di server OpenAI
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Resource tidak ditemukan di OpenAI: {str(e)}")
    except BadRequestError as e:
        # Menangani request yang ditolak oleh validasi OpenAI
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Permintaan tidak valid: {str(e)}")
    except AuthenticationError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autentikasi ke OpenAI gagal. Periksa API Key.")
    except RateLimitError:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Batas kuota/rate limit OpenAI tercapai.")
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except OpenAIError as e:
        logger.error(f"OpenAI API error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Kesalahan layanan pihak OpenAI: {str(e)}")
    except Exception as e:
        logger.error(f"Unhandled error in chat endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Terjadi kesalahan internal pada server.")
```

---

## 6. Langkah Selanjutnya (Action Plan)

1. **Terapkan Perbaikan Kode**: Kamu bisa mulai mengganti/memperbarui kode pada file `schemas.py`, `services.py`, dan `main.py` menggunakan referensi kode di atas.
2. **Pasang Library Rate Limiter**: Sangat disarankan menginstal library seperti `slowapi` (`pip install slowapi`) untuk melindungmu dari serangan kehabisan kuota.
3. **Uji Validasi Input**: Coba kirimkan request dengan `thread_id` yang salah dari Postman/Swagger UI dan pastikan server mengembalikan error `404 Not Found` (bukan `502`).
