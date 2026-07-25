import logging
from typing import Tuple, Optional
from openai import AsyncOpenAI, OpenAIError, RateLimitError, AuthenticationError, NotFoundError, BadRequestError
from app.config import settings

# Konfigurasi logging
logger = logging.getLogger("api.services")

class OpenAIService:
    """
    Layanan untuk berkomunikasi dengan OpenAI Assistants API (v2) secara asinkron.
    """
    def __init__(self, client: Optional[AsyncOpenAI] = None):
        # Inisialisasi client secara dinamis untuk menghindari issue 'Event loop is closed' saat runtime/multiprocess
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)
        self.default_assistant_id = settings.openai_assistant_id

    async def create_thread(self) -> str:
        """
        Membuat Thread percakapan baru di server OpenAI.
        
        Returns:
            str: thread_id
        """
        try:
            thread = await self.client.beta.threads.create()
            logger.info(f"Berhasil membuat thread baru: {thread.id}")
            return thread.id
        except AuthenticationError as e:
            logger.error("Autentikasi OpenAI gagal. Periksa OPENAI_API_KEY.")
            raise e
        except Exception as e:
            logger.error(f"Error saat membuat thread OpenAI: {str(e)}")
            raise e

    async def chat_with_assistant(
        self, 
        message: str, 
        thread_id: Optional[str] = None, 
        assistant_id: Optional[str] = None
    ) -> Tuple[str, str, str, str]:
        """
        Mengirim pesan ke OpenAI Assistant, menjalankan run, dan mengambil balasan terbaru.

        Args:
            message (str): Teks input dari user.
            thread_id (Optional[str]): ID thread aktif. Jika None, akan dibuatkan thread baru.
            assistant_id (Optional[str]): Override ID Assistant. Jika None, pakai dari settings.

        Returns:
            Tuple[str, str, str, str]: (response_text, thread_id, run_id, status)
        """
        # 1. Tentukan Assistant ID
        target_assistant_id = assistant_id or self.default_assistant_id
        if not target_assistant_id or target_assistant_id == "asst_your_assistant_id_here":
            raise ValueError("OPENAI_ASSISTANT_ID belum dikonfigurasi dengan benar di file .env atau request.")

        # 2. Buat Thread jika belum ada
        if not thread_id:
            thread_id = await self.create_thread()

        try:
            # 3. Tambahkan pesan baru dari user ke dalam Thread
            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message
            )
            logger.info(f"Pesan user ditambahkan ke thread {thread_id}")

            # 4. Buat dan jalankan Run (menggunakan create_and_poll dari SDK resmi v2)
            run = await self.client.beta.threads.runs.create_and_poll(
                thread_id=thread_id,
                assistant_id=target_assistant_id,
                poll_interval_ms=1000
            )
            logger.info(f"Run {run.id} selesai dengan status: {run.status}")

            if run.status != "completed":
                error_detail = f"Run tidak selesai (Status: {run.status})."
                if hasattr(run, "last_error") and run.last_error:
                    error_detail += f" Detail: {run.last_error}"
                logger.error(error_detail)
                raise RuntimeError(error_detail)

            # 5. Ambil riwayat pesan dari Thread
            messages = await self.client.beta.threads.messages.list(
                thread_id=thread_id,
                order="desc",
                limit=10
            )

            response_text = ""
            for msg in messages.data:
                # PENTING: Hanya ambil pesan yang cocok dengan run_id saat ini agar tidak mengambil balasan lama
                if msg.role == "assistant" and msg.run_id == run.id:
                    for content_block in msg.content:
                        if content_block.type == "text":
                            response_text += content_block.text.value + "\n"
                    break
            
            # Jika run berhasil tapi tidak ada teks yang dikembalikan oleh run tersebut
            if not response_text.strip():
                raise RuntimeError("Assistant selesai memproses, namun tidak menghasilkan jawaban teks untuk run saat ini.")

            return response_text.strip(), thread_id, run.id, run.status

        except RateLimitError as e:
            logger.error(f"Rate limit exceeded: {str(e)}")
            raise e
        except AuthenticationError as e:
            logger.error(f"Authentication error: {str(e)}")
            raise e
        except (NotFoundError, BadRequestError) as e:
            logger.error(f"Request error OpenAI: {str(e)}")
            raise e
        except OpenAIError as e:
            logger.error(f"OpenAI API Error: {str(e)}")
            raise e

# Dependency provider untuk diinjeksi ke endpoint FastAPI (Dependency Injection)
def get_openai_service() -> OpenAIService:
    return OpenAIService()
