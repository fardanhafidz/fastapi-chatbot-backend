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
