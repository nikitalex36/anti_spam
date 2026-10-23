import asyncio
from aiogram import Bot, Dispatcher
from config import TOKEN
from proxy1 import PROXY
from aiogram.client.session.aiohttp import AiohttpSession
from apps.handlers import router
session = AiohttpSession(proxy=PROXY) 
bot = Bot(token=TOKEN, session=session)
dp = Dispatcher()





async def main():
    dp.include_router(router)
    await dp.start_polling(bot, allowed_updates=['message', 'chat_member', 'callback_query'])


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

