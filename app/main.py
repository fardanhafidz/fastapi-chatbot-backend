import logging
from fastapi import FastAPI, HTTPException, status, Depends, Security, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from openai import AuthenticationError, RateLimitError, OpenAIError, NotFoundError, BadRequestError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.schemas import ChatRequest, ChatResponse, ConversationCreateResponse, HealthResponse
from app.services import OpenAIService, get_openai_service

logger = logging.getLogger("api.main")

# Inisialisasi Rate Limiter (slowapi) sesuai instruksi keamanan bagian 3.2 & 6.4
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=settings.app_name,
    description="Backend API untuk Chatbot AI berbasis FastAPI dan OpenAI Responses API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Registrasi exception handler untuk Rate Limit
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Proteksi API Key internal
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    if settings.internal_api_key and settings.internal_api_key.strip():
        if not api_key or api_key != settings.internal_api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")

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

@app.post("/api/v1/conversations", response_model=ConversationCreateResponse, status_code=status.HTTP_201_CREATED, tags=["Conversations"], dependencies=[Depends(verify_api_key)])
@limiter.limit("15/minute")
async def create_new_conversation(request: Request, service: OpenAIService = Depends(get_openai_service)):
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

@app.post("/api/v1/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK, tags=["Chat"], dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
async def chat_endpoint(
    request: Request,
    payload: ChatRequest, 
    service: OpenAIService = Depends(get_openai_service)
):
    """
    Endpoint utama berinteraksi dengan AI menggunakan Responses API terbaru (tanpa polling!).
    """
    try:
        output_text, response_id, conv_id = await service.chat_with_ai(
            message=payload.message,
            conversation_id=payload.conversation_id,
            previous_response_id=payload.previous_response_id
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
