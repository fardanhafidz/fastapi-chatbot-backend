from typing import Optional
from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    """
    Skema request dari pengguna untuk mengirim pesan ke chatbot.
    Sudah dimigrasikan ke OpenAI Responses API, namun tetap mendukung field 'thread_id' (legacy) 
    agar kompatibel dengan frontend yang belum diperbarui.
    """
    message: str = Field(
        ..., 
        min_length=1, 
        max_length=4000, 
        description="Pesan atau pertanyaan dari pengguna (maksimal 4000 karakter)"
    )
    previous_response_id: Optional[str] = Field(
        None, 
        description="ID dari respons OpenAI sebelumnya (response.id) untuk melanjutkan percakapan secara stateful. Kosongkan untuk mulai percakapan baru."
    )
    thread_id: Optional[str] = Field(
        None, 
        description="[Deprecated] Field lama untuk kompatibilitas mundur dengan arsitektur Assistants API. Akan otomatis dipetakan ke previous_response_id jika diisi."
    )
    instructions: Optional[str] = Field(
        None, 
        description="Override instruksi sistem (system prompt) untuk sesi percakapan ini."
    )

    @model_validator(mode="after")
    def map_legacy_fields(self) -> "ChatRequest":
        """
        Jika frontend masih mengirimkan 'thread_id' (karena migration in-progress) dan belum 
        mengirimkan 'previous_response_id', petakan nilainya secara otomatis.
        """
        if self.thread_id and not self.previous_response_id:
            # Petakan thread_id lama sebagai previous_response_id
            self.previous_response_id = self.thread_id
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Halo, bisakah kamu jelaskan apa itu hukum termodinamika?",
                "previous_response_id": "resp_abc123xyz"
            }
        }
    }


class ChatResponse(BaseModel):
    """
    Skema balasan dari chatbot menggunakan arsitektur modern OpenAI Responses API.
    """
    response: str = Field(..., description="Jawaban teks dari AI")
    response_id: str = Field(..., description="ID dari respons saat ini (resp_...). Gunakan ID ini sebagai 'previous_response_id' pada request berikutnya untuk melanjutkan obrolan.")
    conversation_id: str = Field(..., description="Alias untuk response_id (mempermudah tracking sesi di frontend)")
    status: str = Field("completed", description="Status eksekusi")

    model_config = {
        "json_schema_extra": {
            "example": {
                "response": "Tentu! Hukum termodinamika pertama menyatakan bahwa energi tidak dapat diciptakan atau dimusnahkan...",
                "response_id": "resp_abc123xyz",
                "conversation_id": "resp_abc123xyz",
                "status": "completed"
            }
        }
    }


class ConversationInitResponse(BaseModel):
    """
    Skema respons untuk inisialisasi sesi percakapan baru.
    Menggantikan skema ThreadCreateResponse pada arsitektur lama.
    """
    conversation_id: str = Field(..., description="ID sesi percakapan / respons yang diinisialisasi")
    message: str = Field("Sesi percakapan baru berhasil diinisialisasi", description="Pesan status")


# Alias untuk backward compatibility dengan rute lama (/api/v1/threads)
ThreadCreateResponse = ConversationInitResponse


class HealthResponse(BaseModel):
    """
    Skema respons untuk pengecekan status server (health check).
    """
    status: str = Field("ok", description="Status servis")
    app_name: str = Field(..., description="Nama aplikasi")
    environment: str = Field(..., description="Lingkungan aktif (development/production)")
    version: str = Field("2.0.0-responses-api", description="Versi API")
