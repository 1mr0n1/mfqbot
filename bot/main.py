import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

from .backend_client import BackendClient, BackendError

load_dotenv()
logging.basicConfig(level=logging.INFO)

TELEGRAM_LIMIT = 4096

router = Router()
backend = BackendClient()


async def model_keyboard(user_id: int) -> InlineKeyboardMarkup:
    models = await backend.list_models()
    current = await backend.get_model(user_id)
    buttons = [
        [InlineKeyboardButton(text=("✅ " if m["key"] == current else "") + m["name"],
                              callback_data=f"model:{m['key']}")]
        for m in models
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Hi! I'm your AI assistant. Just send me a message.\n\n"
        "/model — choose the AI model\n"
        "/reset — start a new conversation"
    )


@router.message(Command("model"))
async def cmd_model(message: Message):
    try:
        kb = await model_keyboard(message.from_user.id)
    except BackendError as e:
        return await message.answer(f"⚠️ {e}")
    await message.answer("Choose a model:", reply_markup=kb)


@router.callback_query(F.data.startswith("model:"))
async def on_model_chosen(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    try:
        await backend.set_model(callback.from_user.id, key)
        kb = await model_keyboard(callback.from_user.id)
    except BackendError as e:
        return await callback.answer(str(e), show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer("Model switched")


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    try:
        await backend.reset(message.from_user.id)
    except BackendError as e:
        return await message.answer(f"⚠️ {e}")
    await message.answer("🧹 Conversation cleared.")


@router.message(F.text)
async def on_text(message: Message, bot: Bot):
    # Keep "typing…" visible while the backend works (Telegram clears it after ~5s).
    async def keep_typing():
        while True:
            await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            await asyncio.sleep(4)

    typing = asyncio.create_task(keep_typing())
    try:
        reply = await backend.chat(message.from_user.id, message.text)
    except BackendError as e:
        reply = f"⚠️ {e}"
    finally:
        typing.cancel()

    for i in range(0, len(reply), TELEGRAM_LIMIT):
        await message.answer(reply[i:i + TELEGRAM_LIMIT])


async def main():
    bot = Bot(os.environ["TELEGRAM_BOT_TOKEN"])
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="model", description="Choose the AI model"),
        BotCommand(command="reset", description="Start a new conversation"),
    ])
    try:
        await dp.start_polling(bot)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
