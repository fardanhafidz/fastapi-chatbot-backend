import logging
from fastapi import FastAPI, HTTPException, status, Depends, Security, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from openai import AuthenticationError, RateLimitError, OpenAIError, NotFoundError, BadRequestError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.schemas import ChatRequest, ChatResponse, ThreadCreateResponse, HealthResponse
from app.services import OpenAIService, get_openai_service

# Konfigurasi logging dasar
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("api.main")

# Inisialisasi Rate Limiter (SlowAPI) berbasis IP Klien
limiter = Limiter(key_func=get_remote_address)

# Inisialisasi FastAPI App
app = FastAPI(
    title=settings.app_name,
    description="Backend API untuk Chatbot AI berbasis FastAPI dan OpenAI Assistants API (Dilengkapi Proteksi Keamanan & Rate Limiter)",
    version="1.0.1",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Registrasi exception handler untuk Rate Limit
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Keamanan: Validasi API Key internal dari header X-API-Key (jika dikonfigurasi di .env)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    """
    Memvalidasi header X-API-Key terhadap INTERNAL_API_KEY dari settings.
    Jika INTERNAL_API_KEY di .env diisi, maka setiap request ke endpoint terproteksi wajib menyertakan key yang sesuai.
    """
    if settings.internal_api_key and settings.internal_api_key.strip():
        if not api_key or api_key != settings.internal_api_key:
            logger.warning("Upaya akses ilegal ditolak (X-API-Key tidak valid atau hilang).")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Kredensial X-API-Key tidak valid atau tidak ditemukan pada header request."
            )

# Konfigurasi CORS Middleware yang Aman
# Memastikan tidak terjadi konflik wildcard '*' dengan allow_credentials=True
allowed_origins = settings.allowed_origins
has_wildcard = "*" in allowed_origins

if has_wildcard and settings.app_env.lower() == "production":
    logger.warning("Peringatan Keamanan: Wildcard CORS '*' terdeteksi di lingkungan produksi!")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False if has_wildcard else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Endpoint untuk memeriksa apakah server berjalan dengan baik (Health Check).
    """
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.app_env,
        version="1.0.1"
    )

@app.post(
    "/api/v1/threads", 
    response_model=ThreadCreateResponse, 
    status_code=status.HTTP_201_CREATED, 
    tags=["Threads"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("10/minute")
async def create_new_thread(
    request: Request,
    service: OpenAIService = Depends(get_openai_service)
):
    """
    Endpoint untuk membuat Thread percakapan OpenAI baru secara manual.
    Dilengkapi proteksi Rate Limit (maks 10/menit) dan pengecekan otentikasi X-API-Key.
    """
    try:
        thread_id = await service.create_thread()
        return ThreadCreateResponse(
            thread_id=thread_id,
            message="Thread percakapan berhasil dibuat"
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi ke OpenAI gagal. Periksa konfigurasi OPENAI_API_KEY di file .env."
        )
    except OpenAIError as e:
        logger.error(f"Gagal membuat thread: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Terjadi kesalahan saat berkomunikasi dengan server OpenAI: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Internal server error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Terjadi kesalahan internal pada server."
        )

@app.post(
    "/api/v1/chat", 
    response_model=ChatResponse, 
    status_code=status.HTTP_200_OK, 
    tags=["Chat"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("20/minute")
async def chat_endpoint(
    request: Request,
    payload: ChatRequest,
    service: OpenAIService = Depends(get_openai_service)
):
    """
    Endpoint utama untuk berinteraksi dengan Chatbot AI Assistant.
    - Dilengkapi proteksi Rate Limit (maks 20/menit) dan pengecekan otentikasi X-API-Key.
    - Validasi regex ID dan batas maksimal teks 4000 karakter.
    - Mengembalikan balasan AI, thread_id, dan run_id.
    """
    try:
        response_text, thread_id, run_id, run_status = await service.chat_with_assistant(
            message=payload.message,
            thread_id=payload.thread_id,
            assistant_id=payload.assistant_id
        )
        return ChatResponse(
            response=response_text,
            thread_id=thread_id,
            run_id=run_id,
            status=run_status
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except NotFoundError as e:
        # Menangani thread_id atau assistant_id yang tidak ditemukan di server OpenAI (HTTP 404)
        logger.warning(f"OpenAI resource not found: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Resource (thread/assistant) tidak ditemukan di OpenAI: {str(e)}"
        )
    except BadRequestError as e:
        # Menangani request yang ditolak oleh validasi OpenAI (HTTP 400)
        logger.warning(f"OpenAI bad request: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Permintaan tidak valid menurut spesifikasi OpenAI: {str(e)}"
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi ke OpenAI gagal. Periksa konfigurasi OPENAI_API_KEY di file .env."
        )
    except RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Batas kuota/rate limit OpenAI telah tercapai. Silakan coba beberapa saat lagi."
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except OpenAIError as e:
        logger.error(f"OpenAI API error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Kesalahan layanan dari pihak OpenAI: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unhandled error in chat endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Terjadi kesalahan internal pada server."
        )
