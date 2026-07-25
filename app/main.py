import logging
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from openai import AuthenticationError, RateLimitError, OpenAIError

from app.config import settings
from app.schemas import ChatRequest, ChatResponse, ThreadCreateResponse, HealthResponse
from app.services import openai_service

# Konfigurasi logging dasar
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("api.main")

# Inisialisasi FastAPI App
app = FastAPI(
    title=settings.app_name,
    description="Backend API untuk Chatbot AI berbasis FastAPI dan OpenAI Assistants API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Konfigurasi CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
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
        version="1.0.0"
    )

@app.post("/api/v1/threads", response_model=ThreadCreateResponse, status_code=status.HTTP_201_CREATED, tags=["Threads"])
async def create_new_thread():
    """
    Endpoint opsional untuk membuat Thread percakapan OpenAI baru secara manual.
    Berguna jika frontend ingin menginisialisasi sesi percakapan sebelum user mengirim pesan pertama.
    """
    try:
        thread_id = await openai_service.create_thread()
        return ThreadCreateResponse(
            thread_id=thread_id,
            message="Thread percakapan berhasil dibuat"
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi ke OpenAI gagal. Periksa konfigurasi OPENAI_API_KEY."
        )
    except OpenAIError as e:
        logger.error(f"Gagal membuat thread: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Terjadi kesalahan saat berkomunikasi dengan server OpenAI: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Internal server error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Terjadi kesalahan internal pada server."
        )

@app.post("/api/v1/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK, tags=["Chat"])
async def chat_endpoint(request: ChatRequest):
    """
    Endpoint utama untuk berinteraksi dengan Chatbot AI Assistant.
    - Mengirim pesan baru ke thread.
    - Menjalankan Assistant run & menunggu hasil (polling otomatis).
    - Mengembalikan balasan AI, thread_id, dan run_id.
    """
    try:
        response_text, thread_id, run_id, run_status = await openai_service.chat_with_assistant(
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi ke OpenAI gagal. Periksa konfigurasi OPENAI_API_KEY di file .env."
        )
    except RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Batas limit request (Rate Limit / Kuota) OpenAI telah tercapai. Silakan coba beberapa saat lagi."
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
