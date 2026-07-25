import logging
from typing import Tuple, Optional
from openai import AsyncOpenAI, OpenAIError, RateLimitError, AuthenticationError, NotFoundError, BadRequestError
from app.config import settings

# Konfigurasi logging
logger = logging.getLogger("api.services")

class OpenAIService:
    """
    Layanan untuk berkomunikasi dengan OpenAI Responses API secara asinkron.
    Arsitektur baru ini jauh lebih bersih, tanpa perlu mekanisme polling thread/run yang rumit.
    Konteks percakapan otomatis dijaga oleh server OpenAI melalui parameter 'previous_response_id'.
    """
    def __init__(self, client: Optional[AsyncOpenAI] = None):
        # Inisialisasi client secara dinamis untuk menghindari issue 'Event loop is closed'
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)

    async def init_conversation(self) -> str:
        """
        Menginisialisasi sesi percakapan kosong baru (opsional, jika frontend ingin mendapatkan ID sesi awal).
        
        Returns:
            str: ID sesi / conversation ID
        """
        try:
            # Membuat pesan penyambutan atau inisialisasi respons awal dengan sistem instruksi
            response = await self.client.responses.create(
                model=settings.openai_model,
                input="Sesi percakapan baru dimulai.",
                instructions=settings.openai_system_instructions
            )
            logger.info(f"Berhasil menginisialisasi sesi percakapan baru dengan ID: {response.id}")
            return response.id
        except AuthenticationError as e:
            logger.error("Autentikasi OpenAI gagal. Periksa OPENAI_API_KEY.")
            raise e
        except Exception as e:
            logger.error(f"Error saat menginisialisasi percakapan OpenAI: {str(e)}")
            raise e

    async def chat_with_responses_api(
        self, 
        message: str, 
        previous_response_id: Optional[str] = None,
        instructions: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """
        Mengirim pesan ke OpenAI menggunakan arsitektur modern Responses API (client.responses.create).

        Args:
            message (str): Teks input dari user.
            previous_response_id (Optional[str]): ID dari response sebelumnya (resp_...) untuk menjaga konteks obrolan.
            instructions (Optional[str]): Override system prompt/instruksi.

        Returns:
            Tuple[str, str, str]: (response_text, response_id, status)
        """
        # Siapkan parameter panggilan Responses API
        params = {
            "model": settings.openai_model,
            "input": message,
        }

        # Jika ada previous_response_id (dari sesi percakapan sebelumnya), sertakan agar memori obrolan bersambung
        if previous_response_id and previous_response_id.strip():
            # Hindari pengiriman ID lama yang keliru berformat 'thread_' jika frontend masih memakai id lama
            if not previous_response_id.startswith("thread_"):
                params["previous_response_id"] = previous_response_id.strip()

        # Gunakan instruksi sistem dari parameter atau fallback ke konfigurasi .env
        target_instructions = instructions or settings.openai_system_instructions
        if target_instructions and target_instructions.strip():
            # Instruksi biasanya diset pada percakapan atau setiap turn
            params["instructions"] = target_instructions.strip()

        try:
            logger.info(f"Memanggil OpenAI Responses API dengan model {settings.openai_model} (previous_response_id: {params.get('previous_response_id')})")
            
            # Panggilan asinkron tunggal tanpa polling run!
            response = await self.client.responses.create(**params)
            logger.info(f"Responses API berhasil. ID Respons baru: {response.id}")

            # Ekstrak teks balasan dari properti output_text
            output_text = getattr(response, "output_text", None) or ""
            
            # Fallback jika output_text kosong, periksa atribut output array
            if not output_text.strip() and hasattr(response, "output") and response.output:
                for item in response.output:
                    if hasattr(item, "content") and item.content:
                        for content_item in item.content:
                            if hasattr(content_item, "text") and content_item.text:
                                output_text += str(content_item.text) + "\n"
                            elif hasattr(content_item, "value") and content_item.value:
                                output_text += str(content_item.value) + "\n"

            if not output_text.strip():
                raise RuntimeError("Model AI selesai memproses, namun tidak menghasilkan jawaban teks yang valid.")

            return output_text.strip(), response.id, "completed"

        except RateLimitError as e:
            logger.error(f"Rate limit exceeded: {str(e)}")
            raise e
        except AuthenticationError as e:
            logger.error(f"Authentication error: {str(e)}")
            raise e
        except (NotFoundError, BadRequestError) as e:
            logger.error(f"Request error OpenAI Responses API: {str(e)}")
            raise e
        except OpenAIError as e:
            logger.error(f"OpenAI API Error: {str(e)}")
            raise e

# Dependency provider untuk diinjeksi ke endpoint FastAPI (Dependency Injection)
def get_openai_service() -> OpenAIService:
    return OpenAIService()
