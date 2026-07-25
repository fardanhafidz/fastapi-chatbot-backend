import logging
from fastapi import FastAPI, HTTPException, status, Depends, Security, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from openai import AuthenticationError, RateLimitError, OpenAIError, NotFoundError, BadRequestError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.schemas import ChatRequest, ChatResponse, ConversationInitResponse, ThreadCreateResponse, HealthResponse
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
    description="Backend API Chatbot AI Modern berbasis FastAPI dan OpenAI Responses API (Dilengkapi Keamanan & Rate Limiter)",
    version="2.0.0-responses-api",
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
        version="2.0.0-responses-api"
    )

@app.post(
    "/api/v1/conversations", 
    response_model=ConversationInitResponse, 
    status_code=status.HTTP_201_CREATED, 
    tags=["Conversations"],
    dependencies=[Depends(verify_api_key)]
)
@app.post(
    "/api/v1/threads", 
    response_model=ThreadCreateResponse, 
    status_code=status.HTTP_201_CREATED, 
    tags=["Conversations (Legacy Alias)"],
    dependencies=[Depends(verify_api_key)],
    include_in_schema=False
)
@limiter.limit("10/minute")
async def init_conversation_endpoint(
    request: Request,
    service: OpenAIService = Depends(get_openai_service)
):
    """
    Endpoint untuk menginisialisasi sesi percakapan baru.
    Mendukung endpoint modern '/api/v1/conversations' dan tetap menjaga backward compatibility dengan '/api/v1/threads'.
    Dilengkapi proteksi Rate Limit (maks 10/menit) dan pengecekan otentikasi X-API-Key.
    """
    try:
        conversation_id = await service.init_conversation()
        return ConversationInitResponse(
            conversation_id=conversation_id,
            message="Sesi percakapan baru berhasil diinisialisasi"
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi ke OpenAI gagal. Periksa konfigurasi OPENAI_API_KEY di file .env."
        )
    except OpenAIError as e:
        logger.error(f"Gagal menginisialisasi percakapan: {str(e)}")
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
    Endpoint utama untuk berinteraksi dengan Chatbot AI menggunakan OpenAI Responses API.
    - Dilengkapi proteksi Rate Limit (maks 20/menit) dan pengecekan otentikasi X-API-Key.
    - Menggunakan 'previous_response_id' untuk meneruskan percakapan sebelumnya secara otomatis tanpa polling rumit.
    - Mendukung kompatibilitas dengan frontend lama yang mengirimkan 'thread_id'.
    """
    try:
        response_text, response_id, run_status = await service.chat_with_responses_api(
            message=payload.message,
            previous_response_id=payload.previous_response_id,
            instructions=payload.instructions
        )
        return ChatResponse(
            response=response_text,
            response_id=response_id,
            conversation_id=response_id,
            status=run_status
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except NotFoundError as e:
        logger.warning(f"OpenAI resource not found: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID respons / sesi sebelumnya tidak ditemukan di server OpenAI: {str(e)}"
        )
    except BadRequestError as e:
        logger.warning(f"OpenAI bad request: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Permintaan tidak valid menurut spesifikasi OpenAI Responses API: {str(e)}"
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
