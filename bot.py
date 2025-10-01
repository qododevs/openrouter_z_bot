import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
import openai
from database import DatabaseManager
from document_processor import DocumentProcessor

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher()

db_manager = DatabaseManager()
doc_processor = DocumentProcessor(db_manager=db_manager)

openai_client = openai.OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT")

clear_context_button = KeyboardButton(text="Очистить контекст")
keyboard = ReplyKeyboardMarkup(
    keyboard=[[clear_context_button]],
    resize_keyboard=True,
    input_field_placeholder="Задайте ваш вопрос..."
)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Здравствуйте! Я ваш персональный косметический консультант. "
        "Я могу помочь вам с выбором косметики, рекомендациями по уходу за кожей "
        "и ответить на вопросы о косметических продуктах. "
        "Задайте ваш вопрос, и я с радостью помогу!",
        reply_markup=keyboard
    )


@dp.message(F.text == "Очистить контекст")
async def clear_context(message: types.Message):
    user_id = message.from_user.id
    db_manager.clear_user_context(user_id)
    await message.answer(
        "Контекст очищен. Теперь мы можем начать наш диалог с чистого листа.",
        reply_markup=keyboard
    )


@dp.message(F.text)
async def process_message(message: types.Message):
    user_id = message.from_user.id
    user_message = message.text

    context = db_manager.get_user_context(user_id)
    relevant_docs = db_manager.search_similar(user_message, k=5)

    context_text = ""
    if relevant_docs:
        context_text = "\n\n".join([doc.page_content for doc in relevant_docs])
        context_text = f"Информация из базы знаний:\n{context_text}\n\n"

    history_text = ""
    if context:
        history_text = "\n".join(
            [f"{'Пользователь' if i % 2 == 0 else 'Ассистент'}: {msg}" for i, msg in enumerate(context)])
        history_text = f"История диалога:\n{history_text}\n\n"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    if context_text:
        messages.append({"role": "system", "content": context_text})

    if history_text:
        messages.append({"role": "system", "content": history_text})

    messages.append({"role": "user", "content": user_message})

    try:
        response = openai_client.chat.completions.create(
            model="deepseek/deepseek-chat-v3.1:free",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )

        answer = response.choices[0].message.content

        new_context = context + [user_message, answer]
        if len(new_context) > 10:
            new_context = new_context[-10:]

        db_manager.update_user_context(user_id, new_context)

        await message.answer(answer, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await message.answer(
            "Извините, произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз.",
            reply_markup=keyboard
        )


async def main():
    doc_processor.process_all_documents()
    logger.info("Запуск бота...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    finally:
        doc_processor.stop()
