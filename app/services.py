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
