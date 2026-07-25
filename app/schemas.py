from typing import Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """
    Skema request dari pengguna untuk mengirim pesan ke chatbot.
    """
    message: str = Field(..., min_length=1, description="Pesan atau pertanyaan dari pengguna")
    thread_id: Optional[str] = Field(None, description="ID Thread OpenAI jika melanjutkan percakapan sebelumnya. Kosongkan untuk percakapan baru.")
    assistant_id: Optional[str] = Field(None, description="Override Assistant ID (opsional jika menggunakan multiple assistants)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Halo, apa yang bisa kamu bantu hari ini?",
                "thread_id": "thread_abc123"
            }
        }
    }


class ChatResponse(BaseModel):
    """
    Skema balasan dari chatbot (OpenAI Assistant).
    """
    response: str = Field(..., description="Jawaban teks dari AI Assistant")
    thread_id: str = Field(..., description="ID Thread percakapan aktif")
    run_id: str = Field(..., description="ID eksekusi run pada OpenAI")
    status: str = Field(..., description="Status akhir dari eksekusi run (e.g. 'completed')")

    model_config = {
        "json_schema_extra": {
            "example": {
                "response": "Halo! Saya adalah asisten AI Anda. Ada yang bisa saya bantu?",
                "thread_id": "thread_abc123",
                "run_id": "run_xyz789",
                "status": "completed"
            }
        }
    }


class ThreadCreateResponse(BaseModel):
    """
    Skema respons untuk pembuatan thread baru secara manual.
    """
    thread_id: str = Field(..., description="ID Thread yang baru saja dibuat di OpenAI")
    message: str = Field("Thread berhasil dibuat", description="Pesan status")


class HealthResponse(BaseModel):
    """
    Skema respons untuk pengecekan status server (health check).
    """
    status: str = Field("ok", description="Status servis")
    app_name: str = Field(..., description="Nama aplikasi")
    environment: str = Field(..., description="Lingkungan aktif (development/production)")
    version: str = Field("1.0.0", description="Versi API")
