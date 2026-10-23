import asyncio
import aiohttp
import logging
from aiogram import Bot, F, Router
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, Command
from aiogram.types import ChatMemberUpdated, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.exceptions import TelegramBadRequest
from config import DEEPSEEK_API_KEY, SPAM_KEYWORDS
router = Router()

timers = {}

logging.basicConfig(
    filename = 'spam.log',
    level = logging.WARNING,
    format = '%(asctime)s | %(levelname)s | %(message)s',
    encoding = 'utf-8'
)
#######################################################################################################################
@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def joined(event: ChatMemberUpdated):
    user_id = event.new_chat_member.user.id
    chat_id = event.chat.id
    try:
        await event.bot.restrict_chat_member(
            chat_id = chat_id,
            user_id = user_id,
            permissions = {"can_send_messages": False}
        )

    except TelegramBadRequest:
        pass

    yanerobot = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='''Я не робот\nI'm not a robot''', callback_data=f'verify_{user_id}')]
        ])
    message = await event.bot.send_message(
        chat_id = chat_id,
        text = 'Нажми на кнопку ниже',
        reply_markup = yanerobot
        )
    task = asyncio.create_task(kick_timeout(event.bot, chat_id, user_id, message.message_id))
    timers[(chat_id, user_id)] = task

async def kick_timeout(bot, chat_id, user_id, message_id):
    await asyncio.sleep(180)
    if (chat_id, user_id) in timers:
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.delete_message(chat_id, message_id)
        except TelegramBadRequest:
            pass
        finally:
            timers.pop((chat_id, user_id), None)



@router.callback_query(F.data.startswith("verify_"))
async def odobreniye(callback: CallbackQuery):
    user_id = int(callback.data.split('_')[1])
    if callback.from_user.id != user_id:
        await callback.answer(f'Это не Ваша кнопка,{callback.from_user.first_name}!', show_alert=True)
        return
    chat_id = callback.message.chat.id
    task = timers.pop((chat_id, user_id), None)
    if task:
        task.cancel()
    try:
        await callback.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions={
                'can_send_messages': True,
                'can_send_media_messages': True,
                'can_send_other_messages': True,
                "can_add_web_page_previews": True
            }
        )
        await callback.answer("Вы прошли проверку!", show_alert=True)
        await callback.message.delete()
    except TelegramBadRequest:
        await callback.answer("Ошибка...", show_alert=True)
#################################################################################################################
current_action_mode = 'notify_admin'

async def get_admin_mentions(bot, chat_id) -> str:
    try:
        admins = await bot.get_chat_administrators(chat_id)
        mentions = []
        for admin in admins:
            if admin.user.is_bot:
                continue
            name = admin.user.first_name
            if admin.user.username:
                name = f'@{admin.user.username}'
            mentions.append(f'[{name}](tg://user?id={admin.user.id})')
            return ', '.join(mentions)
    except TelegramBadRequest:
        return "@admin"

@router.message(Command('mode'))
async def mode(message):
    try:
        member = await message.bot.get_chat_member(chat_id = message.chat.id, user_id = message.from_user.id)
        if member.status not in ['administrator', 'creator']:
            return
    except TelegramBadRequest:
        pass
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text = 'Уведомлять', callback_data= 'set_mode_notify_admin'),
            InlineKeyboardButton(text = 'Удалять', callback_data= 'set_mode_delete')
        ]
    ])
    await message.answer(
        f'Текущий режим: {current_action_mode}\n\nВыбрать новый:',
        reply_markup = keyboard
    )

@router.callback_query(F.data.startswith('set_mode_'))
async def set_mode(callback):
    global current_action_mode
    try:
        member = await callback.bot.get_chat_member(chat_id = callback.message.chat.id, user_id = callback.from_user.id)
        if member.status not in ['administrator', 'creator']:
            await callback.answer('Доступно только администраторам!', show_alert = True)
            return
    except TelegramBadRequest:
        pass
    new_mode = callback.data.replace('set_mode_', '')
    current_action_mode = new_mode
    await callback.answer(f'Режим изменен на {current_action_mode}', show_alert = True)
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

async def check_with_deepseek(text: str) -> bool:
    url = 'https://api.deepseek.com/chat/completions'
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        
    }
    payload = {
        'model' : 'deepseek-chat',
        'messages' : [
            {
                'role':'user',
                'content':f'Является ли следующее сообщение спамом или вредоносным? Ответь только "да" или "нет". Сообщение: {text}'
            }
        ],
        'temperature': 0.0
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=8) as response:
                if response.status == 200:
                    data = await response.json()
                    answer = data['choises'][0]['message']['content'].strip().lower()
                    return 'да' in answer
                else:
                    logging.error(f'Ошибка DeepSeek: {response.status}')
                    return False
    except Exception as e:
        logging.error(f'Ошибка при запросе к DeepSeek: {e}')
        return False 


@router.message(F.text)
async def check_spam(message):
    if message.text.startswith('/'):
        return
    if message.from_user.is_bot:
        return
    text_lower = message.text.lower()
    sovpadeniye = any(keyword in text_lower for keyword in SPAM_KEYWORDS)
    if not sovpadeniye:
        return
    spam = await check_with_deepseek(message.text)
    if spam:
        log = f'user_id={message.from_user.id} | username={message.from_user.username} | text={message.text}'
        logging.warning(log)
        chat_id_str = str(message.chat.id).replace('-100','')
        link = f'https://t.me/c/{chat_id_str}/{message.message_id}'
        if current_action_mode == 'delete':
            try:
                await message.delete()
            except TelegramBadRequest:
                pass
        elif current_action_mode == 'notify_admin':
            admins_tag = await get_admin_mentions(message.bot, message.chat.id)
            username = f'@{message.from_user.username}' if message.from_user.username else message.from_user.firstname
            await message.reply(
                f'{admins_tag}, спам от пользователя {username}: [ссылка на сообщение] ({link})',
                parse_mode = 'Markdown'
            )



    


