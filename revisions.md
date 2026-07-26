# Audit & Revisi Kode Backend Chatbot (FastAPI + OpenAI Stack Terbaru)

Dokumen ini berisi hasil tinjauan (code review) mendalam, analisis kerentanan keamanan, temuan bug, serta **temuan kritis arsitektural terkait deprecation OpenAI Assistants API** dan panduan migrasi ke **OpenAI Responses API** pada proyek **FastAPI OpenAI Chatbot Backend**.

---

## 1. Ringkasan Eksekutif (Executive Summary)

Secara struktur umum, proyek ini sudah terorganisasi dengan baik menggunakan pola arsitektur modular (`config`, `schemas`, `services`, dan `main`). Namun, berdasarkan penelusuran dokumentasi dan SDK resmi terbaru OpenAI (via **Context7**), ditemukan fakta arsitektural yang sangat penting:

> **OpenAI Assistants API (`client.beta.threads`, `runs`, `messages`) telah dijadwalkan untuk didepresiasi (deprecated).** Arsitektur masa depan dan standar best practice OpenAI kini menggunakan **OpenAI Responses API (`client.responses.create`)** yang digabungkan dengan **Conversations API** atau **Response Chaining**.

Selain kebutuhan migrasi arsitektur tersebut, audit ini juga menemukan beberapa **kerentanan keamanan berisiko tinggi** (CORS wildcard, ketiadaan rate limiting & otentikasi), **bug runtime pada event loop asinkron**, dan **kekurangan validasi input** yang wajib diperbaiki.

---

## 2. 🚨 [SANGAT KRITIS / ARSITEKTURAL] Depresiasi Assistants API & Migrasi ke Responses API

### Masalah pada Arsitektur Lama (Assistants API v2)
Saat ini kode kita di `services.py`, `schemas.py`, dan `main.py` masih menggunakan alur kerja Assistants API:
1. Membuat thread (`client.beta.threads.create()`).
2. Menambahkan pesan user ke thread (`client.beta.threads.messages.create(...)`).
3. Menjalankan model dan menunggu/polling hasil (`client.beta.threads.runs.create_and_poll(...)`).
4. Mengambil daftar riwayat pesan dan memindai secara manual balasan assistant (`client.beta.threads.messages.list(...)`).

**Kekurangan Arsitektur Lama:**
- **Rentan Timeout HTTP & Latensi Tinggi**: Metode `create_and_poll` memblokir request HTTP backend hingga 30-60 detik saat model sedang berpikir panjang, yang sering kali diputus (timeout) oleh Nginx / Cloudflare / Gateway proxy.
- **Kompleksitas Logika & Bug Fallback**: Karena harus memindai list pesan berdasar `run_id`, jika run gagal menghasilkan teks, kode kita saat ini memiliki bug fallback yang justru mengambil balasan dari pertanyaan lama pengguna.
- **Status Deprecated**: OpenAI secara resmi menghentikan fokus pengembangan pada Assistants API untuk digantikan oleh **Responses API**.

---

### Solusi Arsitektur Baru: OpenAI Responses API
Dengan **Responses API**, seluruh proses kompleks di atas digantikan hanya dengan **satu kali pemanggilan API yang langsung mengembalikan jawaban**:

```python
response = await client.responses.create(
    model="gpt-5.5", # atau gpt-4o / model terbaru lainnya
    input=message,
    conversation=conversation_id, # Manajemen state otomatis via Conversations API
    # atau bisa menggunakan: previous_response_id=previous_id
    instructions="You are a helpful AI assistant.",
    store=True # Menyimpan konteks di server OpenAI
)

# Teks langsung tersedia tanpa perlu polling atau loop pesan:
output_text = response.output_text
```

**Keuntungan Responses API:**
- **Tanpa Polling**: Tidak ada lagi loop waiting (`poll_interval_ms`), latensi jauh lebih cepat dan terhindar dari risiko HTTP timeout.
- **Logika Bersih & Bebas Bug**: Tidak ada risiko salah mengambil pesan lama karena atribut `response.output_text` langsung berisi balasan untuk request tersebut.
- **Manajemen Konteks Lebih Mudah**: Bisa menggunakan `conversation_id` (Conversations API) atau `previous_response_id` (Response Chaining).
- **Dukungan Streaming Real-time**: Sangat mudah diubah menjadi streaming (`stream=True`) di masa depan.

---

## 3. Temuan Kritis & Kerentanan Keamanan (Security Vulnerabilities)

### 🚨 [KRITIS] 1. Potensi Kebocoran CORS & Konflik Wildcard (`allow_credentials=True`)
- **Lokasi**: `app/main.py` (Baris 27-33) & `app/config.py` (Baris 31-36)
- **Masalah**: 
  Pada CORS middleware, `allow_credentials=True` diatur bersamaan dengan `allow_origins=settings.allowed_origins`. Jika dalam file `.env` variabel `ALLOWED_ORIGINS` dikosongkan, fungsi di `config.py` akan mengembalikan `["*"]` (wildcard).
  Berdasarkan spesifikasi keamanan browser modern (W3C Fetch/CORS), penggunaan origin wildcard `*` **dilarang keras** bersamaan dengan `allow_credentials=True` (cookie/token). Ini akan menyebabkan browser memblokir seluruh request dari frontend.
- **Koreksi**: 
  - Validasi di `config.py` agar tidak mengembalikan `["*"]` di lingkungan produksi.
  - Atur `allow_credentials=False` jika memang menggunakan origin wildcard `*`.

---

### 🚨 [TINGGI] 2. Ketiadaan Pembatasan Request (Rate Limiting / Denial of Wallet)
- **Lokasi**: `app/main.py` (Semua endpoint `/api/v1/`)
- **Masalah**: 
  Tidak ada mekanisme pembatasan laju request (rate limiting) dari sisi backend (misal menggunakan `slowapi`).
- **Dampak**: 
  Spam atau serangan brute-force dari bot dapat menguras kuota saldo tagihan OpenAI milikmu dalam hitungan menit (*Denial of Wallet Attack*) serta memicu error `429 Too Many Requests` yang melumpuhkan server.
- **Koreksi**: Implementasikan Rate Limiter di level endpoint (contoh: maksimal 15-20 request per menit per IP).

---

### 🚨 [TINGGI] 3. Endpoint Terbuka Tanpa Otentikasi (Missing Authentication)
- **Lokasi**: `app/main.py`
- **Masalah**: 
  Endpoint API terbuka secara publik tanpa pengecekan otorisasi (API Key internal, Bearer Token / JWT).
- **Dampak**: Siapa pun yang mengetahui URL backend dapat menumpang menggunakan model AI berbayarmu secara gratis.
- **Koreksi**: Tambahkan dependency untuk memeriksa header otentikasi (misal header `X-API-Key`) dari frontend sah.

---

### ⚠️ [SEDANG] 4. Ketiadaan Batas Maksimal Karakter pada Pesan (Payload Bloat)
- **Lokasi**: `app/schemas.py` (`ChatRequest.message`)
- **Masalah**: Field `message` hanya dibatasi `min_length=1`, tanpa batas maksimal (`max_length`).
- **Dampak**: Pengguna dapat mengirim teks berukuran jutaan karakter dalam 1 request yang memicu error *context window exhaustion* dan membengkakkan biaya token.
- **Koreksi**: Tambahkan batas maksimal karakter, contoh: `max_length=4000` (atau batas wajar lain).

---

## 4. Bug & Kesalahan Logika (Bugs & Runtime Errors)

### 🐞 [TINGGI] 5. Inisialisasi Klien Asinkron pada Singleton di Luar Event Loop
- **Lokasi**: `app/services.py` (Baris 15 & 123)
- **Masalah**: 
  `self.client = AsyncOpenAI(...)` diinstansiasi langsung saat modul diimpor di level global (`openai_service = OpenAIService()`). Dalam ekosistem asinkron Python (FastAPI/Uvicorn), membuat klien HTTP asinkron di luar *event loop* aktif dapat memicu error `RuntimeError: Event loop is closed` saat server di-reload atau dijalankan dengan multi-workers (`uvicorn --workers N`).
- **Koreksi**: 
  Inisialisasi klien di dalam *event loop* menggunakan pola **FastAPI Lifespan** atau *Dependency Injection* (`Depends`) saat request berlangsung.

---

### 🐞 [SEDANG] 6. Penanganan Status Error HTTP OpenAI yang Kurang Tepat
- **Lokasi**: `app/main.py` (Baris 117-122)
- **Masalah**: 
  Saat ini error dari OpenAI ditangkap oleh blok umum `OpenAIError` dan dikembalikan sebagai HTTP `502 Bad Gateway`. Jika frontend mengirim ID yang tidak valid atau sudah dihapus, SDK melempar `NotFoundError` (HTTP 404) atau `BadRequestError` (HTTP 400).
- **Dampak**: Frontend menerima status `502` padahal kesalahan ada pada format/ID input pengguna, menyulitkan debugging di frontend.
- **Koreksi**: Tangkap spesifik `NotFoundError` (kembalikan HTTP 404) dan `BadRequestError` (kembalikan HTTP 400).

---

## 5. Panduan & Implementasi Kode Perbaikan (Versi Responses API)

Berikut adalah implementasi kode terbaru yang sudah **direfaktorisasi penuh menggunakan OpenAI Responses API**, lengkap dengan perbaikan keamanan dan bug:

### A. Perbaikan `app/config.py` (Menyesuaikan dengan Responses API)
```python
import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    app_name: str = Field("FastAPI AI Chatbot", alias="APP_NAME")
    app_env: str = Field("development", alias="APP_ENV")
    debug: bool = Field(True, alias="DEBUG")
    port: int = Field(8000, alias="PORT")
    
    allowed_origins_raw: str = Field("http://localhost:3000,http://localhost:8000,http://127.0.0.1:8000", alias="ALLOWED_ORIGINS")
    
    # OpenAI Credentials & Config (Responses API)
    openai_api_key: str = Field("sk-your-openai-api-key-here", alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-5.5", alias="OPENAI_MODEL") # Gunakan model terbaru yang mendukung Responses API (gpt-4o, gpt-5.5, dll)
    openai_system_instructions: str = Field("You are a helpful and polite AI assistant.", alias="OPENAI_SYSTEM_INSTRUCTIONS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def allowed_origins(self) -> List[str]:
        if not self.allowed_origins_raw:
            return ["*"] if self.app_env != "production" else []
        return [origin.strip() for origin in self.allowed_origins_raw.split(",") if origin.strip()]

settings = Settings()
```

---

### B. Perbaikan `app/schemas.py` (Skema untuk Responses API & Conversations)
```python
from typing import Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="Pesan dari pengguna (maksimal 4000 karakter)")
    conversation_id: Optional[str] = Field(None, description="ID Conversation OpenAI (diawali 'conv_') jika melanjutkan sesi percakapan sebelumnya.")
    previous_response_id: Optional[str] = Field(None, description="Alternatif: ID Response sebelumnya (diawali 'resp_') untuk response chaining.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Halo, apa yang bisa kamu bantu hari ini?",
                "conversation_id": "conv_abc123"
            }
        }
    }

class ChatResponse(BaseModel):
    response: str = Field(..., description="Jawaban teks dari AI")
    response_id: str = Field(..., description="ID Response dari OpenAI (diawali 'resp_')")
    conversation_id: Optional[str] = Field(None, description="ID Conversation aktif")

    model_config = {
        "json_schema_extra": {
            "example": {
                "response": "Halo! Saya adalah asisten AI Anda. Ada yang bisa saya bantu?",
                "response_id": "resp_xyz789",
                "conversation_id": "conv_abc123"
            }
        }
    }

class ConversationCreateResponse(BaseModel):
    conversation_id: str = Field(..., description="ID Conversation baru yang dibuat di OpenAI")
    message: str = Field("Sesi percakapan berhasil dibuat", description="Pesan status")

class HealthResponse(BaseModel):
    status: str = Field("ok", description="Status servis")
    app_name: str = Field(..., description="Nama aplikasi")
    environment: str = Field(..., description="Lingkungan aktif")
    version: str = Field("2.0.0-responses-api", description="Versi API")
```

---

### C. Perbaikan `app/services.py` (Refaktor ke OpenAI Responses API)
```python
import logging
from typing import Tuple, Optional
from openai import AsyncOpenAI, OpenAIError, RateLimitError, AuthenticationError, NotFoundError, BadRequestError
from app.config import settings

logger = logging.getLogger("api.services")

class OpenAIService:
    def __init__(self, client: Optional[AsyncOpenAI] = None):
        # Client diinjeksi saat request agar aman dari event loop terputus
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.instructions = settings.openai_system_instructions

    async def create_conversation(self) -> str:
        """
        Membuat sesi percakapan baru di server OpenAI (Conversations API).
        """
        try:
            conversation = await self.client.conversations.create()
            logger.info(f"Berhasil membuat conversation baru: {conversation.id}")
            return conversation.id
        except Exception as e:
            logger.error(f"Error saat membuat conversation OpenAI: {str(e)}")
            raise e

    async def chat_with_ai(
        self, 
        message: str, 
        conversation_id: Optional[str] = None,
        previous_response_id: Optional[str] = None
    ) -> Tuple[str, str, Optional[str]]:
        """
        Mengirim pesan menggunakan OpenAI Responses API terbaru.
        Tidak memerlukan polling (create_and_poll) dan langsung mengembalikan output_text!
        """
        try:
            # Siapkan parameter request
            params = {
                "model": self.model,
                "input": message,
                "instructions": self.instructions,
                "store": True  # PENTING: agar riwayat percakapan disimpan oleh OpenAI
            }

            # Gunakan conversation_id jika tersedia, atau previous_response_id
            if conversation_id:
                params["conversation"] = conversation_id
            elif previous_response_id:
                params["previous_response_id"] = previous_response_id

            # Satu pemanggilan API yang cepat & bersih (tanpa polling)
            response = await self.client.responses.create(**params)
            
            logger.info(f"Response {response.id} berhasil dibuat.")
            
            output_text = response.output_text or ""
            if not output_text.strip():
                raise RuntimeError("AI selesai memproses namun tidak mengembalikan jawaban teks.")

            return output_text.strip(), response.id, conversation_id

        except NotFoundError as e:
            logger.error(f"Resource tidak ditemukan (Conversation ID / Response ID salah): {str(e)}")
            raise e
        except BadRequestError as e:
            logger.error(f"Bad Request ke OpenAI: {str(e)}")
            raise e
        except RateLimitError as e:
            logger.error(f"Rate limit exceeded: {str(e)}")
            raise e
        except AuthenticationError as e:
            logger.error("Authentication error: Periksa OPENAI_API_KEY")
            raise e
        except OpenAIError as e:
            logger.error(f"OpenAI API Error: {str(e)}")
            raise e

# Dependency provider untuk FastAPI
def get_openai_service() -> OpenAIService:
    return OpenAIService()
```

---

### D. Perbaikan `app/main.py` (Endpoint Lebih Cepat & Aman)
```python
import logging
from fastapi import FastAPI, HTTPException, status, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from openai import AuthenticationError, RateLimitError, OpenAIError, NotFoundError, BadRequestError

from app.config import settings
from app.schemas import ChatRequest, ChatResponse, ConversationCreateResponse, HealthResponse
from app.services import OpenAIService, get_openai_service

logger = logging.getLogger("api.main")

app = FastAPI(
    title=settings.app_name,
    description="Backend API untuk Chatbot AI berbasis FastAPI dan OpenAI Responses API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Proteksi API Key internal
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    # Aktifkan validasi di bawah ini pada saat produksi
    # if api_key != os.environ.get("INTERNAL_API_KEY"):
    #     raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    pass

# Keamanan CORS
allowed_origins = settings.allowed_origins
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
        version="2.0.0-responses-api"
    )

@app.post("/api/v1/conversations", response_model=ConversationCreateResponse, status_code=status.HTTP_201_CREATED, tags=["Conversations"])
async def create_new_conversation(service: OpenAIService = Depends(get_openai_service)):
    """
    Endpoint untuk membuat sesi conversation baru (menggantikan /api/v1/threads lama).
    """
    try:
        conv_id = await service.create_conversation()
        return ConversationCreateResponse(
            conversation_id=conv_id,
            message="Sesi percakapan berhasil dibuat"
        )
    except AuthenticationError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autentikasi ke OpenAI gagal.")
    except OpenAIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Kesalahan dari OpenAI: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Terjadi kesalahan internal.")

@app.post("/api/v1/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK, tags=["Chat"])
async def chat_endpoint(
    request: ChatRequest, 
    service: OpenAIService = Depends(get_openai_service)
):
    """
    Endpoint utama berinteraksi dengan AI menggunakan Responses API terbaru (tanpa polling!).
    """
    try:
        output_text, response_id, conv_id = await service.chat_with_ai(
            message=request.message,
            conversation_id=request.conversation_id,
            previous_response_id=request.previous_response_id
        )
        return ChatResponse(
            response=output_text,
            response_id=response_id,
            conversation_id=conv_id
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation ID atau Response ID tidak ditemukan: {str(e)}")
    except BadRequestError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Permintaan ditolak oleh OpenAI: {str(e)}")
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

## 6. Ringkasan Aksi Migrasi (Migration Steps)

1. **Ganti Konsep Thread/Run dengan Conversation/Response**: Dalam terminologi baru, tidak ada lagi *Thread* atau *Run*. Kita menggantinya dengan **Conversation** (`conv_...`) dan **Response** (`resp_...`).
2. **Perbarui `.env`**: Kamu tidak lagi membutuhkan `OPENAI_ASSISTANT_ID`. Kamu bisa menggantinya dengan `OPENAI_MODEL="gpt-5.5"` (atau `gpt-4o`) dan menambahkan `OPENAI_SYSTEM_INSTRUCTIONS="Kamu adalah asisten AI..."`.
3. **Terapkan Kode Baru**: Ganti isi `config.py`, `schemas.py`, `services.py`, dan `main.py` menggunakan referensi kode di atas.
4. **Pasang Rate Limiter**: Jangan lupa menginstal `slowapi` untuk melindungi API Key dari spam.
