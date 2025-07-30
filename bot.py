import json
import os
import requests
import asyncio
import logging
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = ""
COMPUTERS_FILE = "computers.json"
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)

#ID
AdminID = 5183977020
AllowedID ={AdminID}
#Не работает
async def send_startup_notification(application):
    """Отправляет уведомление администратору о запуске бота"""
    try:
        # Убедимся, что AdminID определен и является допустимым числом
        admin_id = AdminID
        if not isinstance(admin_id, int) or admin_id <= 0:
            logger.warning("AdminID не установлен или недействителен. Уведомление не отправлено.")
            return

        await application.bot.send_message(
            chat_id=admin_id,
            text="🤖 Бот успешно запущен и готов к работе!"
        )
        logger.info(f"Уведомление о запуске отправлено администратору {admin_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления администратору: {e}")

# Исправленная функция post_init в bot.txt
async def post_init(application):
    """Функция для пост-инициализации"""
    await application.bot.set_my_commands([
        ("start", "Запустить бота"),
        ("cmd", "Войти в режим командной строки"),
        ("history", "Показать историю команд"),
        ("cancel", "Отменить текущую команду")
    ])
    # Отправка уведомления о запуске
    await send_startup_notification(application) # <-- Добавлен вызов функции
    logger.info("Бот успешно запущен")

# Глобальные переменные для управления командами
ACTIVE_COMMANDS = {}
COMMAND_HISTORY = {}

def load_computers():
    if not os.path.exists(COMPUTERS_FILE):
        return {}
    try:
        with open(COMPUTERS_FILE, "r", encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки файла компьютеров: {e}")
        return {}

async def check_computer_status(ip: str) -> bool:
    try:
        response = requests.get(f'http://{ip}:5000/status', timeout=5)
        return response.status_code == 200
    except Exception as e:

        logger.error(f"Ошибка проверки статуса компьютера {ip}: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): # <-- context приходит сюда как аргумент
    try:
        computers = load_computers()
        if not computers:
            await update.message.reply_text("🔍 Нет доступных компьютеров")
            return
        status_messages = []
        for name, ip in computers.items():
            is_online = await check_computer_status(ip) # <-- Эта функция была исправлена
            status = "🟢 Онлайн" if is_online else "🔴 Оффлайн"
            status_messages.append(f"{name} ({ip}) - {status}")
        await update.message.reply_text("📊 Статус компьютеров:\n" + "\n".join(status_messages)) # Исправил \ на \n
        
        keyboard = [
            [InlineKeyboardButton(f"{name} ({ip})", callback_data=f"select_{name}")]
            for name, ip in computers.items()
        ]
        await update.message.reply_text(
            "🖥 Выберите компьютер:",
            reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Ошибка в команде start: {e}") # <-- Больше не используем context в логе
        await update.message.reply_text("❌ Произошла ошибка при обработке команды")


async def show_processes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ip = context.user_data.get('selected_pc')
        if not ip:
            await update.message.reply_text('❌ Компьютер не выбран!')
            return
        
        message = await update.message.reply_text("🔄 Получаем список процессов...")
        
        response = requests.post(
            f'http://{ip}:5000/process',
            json={'action': 'list'},
            timeout=20
        )
        
        if response.status_code != 200:
            raise Exception('Сервер вернул ошибку')
            
        data = response.json()
        if data.get('status') != 'success':
            raise Exception(data.get('message', 'Неизвестная ошибка'))
        
        processes = data.get('processes', [])
        if not processes:
            await message.edit_text('ℹ Нет запущенных процессов')
            return
        
        chunks = []
        current_chunk = []
        current_length = 0
        
        header = "📊 Все процессы (сортировка по памяти):\nPID | Имя | Пользователь | CPU% | Память(MB)\n"
        current_chunk.append(header)
        current_length += len(header)
        
        for proc in processes:
            line = f"{proc['pid']} | {proc['name']} | {proc['user']} | {proc['cpu']}% | {proc['memory']}MB\n"
            if current_length + len(line) > 4000:
                chunks.append(''.join(current_chunk))
                current_chunk = [line]
                current_length = len(line)
            else:
                current_chunk.append(line)
                current_length += len(line)
        
        if current_chunk:
            chunks.append(''.join(current_chunk))
        
        await message.delete()
        first_message = chunks[0] + f"\nВсего процессов: {len(processes)}"
        sent_message = await update.message.reply_text(first_message)
        
        if len(chunks) > 1:
            context.user_data['process_chunks'] = chunks
            context.user_data['current_chunk'] = 0
            context.user_data['process_message_id'] = sent_message.message_id
            
            keyboard = [
                [InlineKeyboardButton("➡ Следующие", callback_data="next_processes")]
            ]
            await sent_message.reply_text(
                "Используйте кнопки для навигации:",
                reply_markup=InlineKeyboardMarkup(keyboard))
        
        instructions = (
            "\n\nДля управления процессами введите:\n"
            "1. По PID: `[PID] [действие]`\n"
            "2. По имени: `[имя.exe] [действие] -n`\n\n"
            "Примеры:\n"
            "`1234 kill` - завершить процесс по PID\n"
            "`explorer.exe kill -n` - завершить все процессы explorer.exe\n"
            "`5678 restart` - перезапустить процесс по PID"
        )
        await update.message.reply_text(instructions, parse_mode='Markdown')
        context.user_data['waiting_process_action'] = True
        
    except Exception as e:
        logger.error(f"Ошибка получения процессов: {e}")
        await update.message.reply_text(f'❌ Ошибка получения процессов: {str(e)}')

async def handle_process_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chunks = context.user_data.get('process_chunks')
    current = context.user_data.get('current_chunk', 0)
    message_id = context.user_data.get('process_message_id')
    
    if not chunks or message_id is None:
        await query.edit_message_text("❌ Данные процессов устарели")
        return
    
    if query.data == "next_processes":
        current += 1
        if current >= len(chunks):
            current = 0
    elif query.data == "prev_processes":
        current -= 1
        if current < 0:
            current = len(chunks) - 1
    
    context.user_data['current_chunk'] = current
    
    keyboard = []
    if len(chunks) > 1:
        keyboard.append([
            InlineKeyboardButton("⬅ Предыдущие", callback_data="prev_processes"),
            InlineKeyboardButton("➡ Следующие", callback_data="next_processes")
        ])
    
    try:
        await query.edit_message_text(
            chunks[current],
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
    except Exception as e:
        logger.error(f"Ошибка пагинации процессов: {e}")
        await query.edit_message_text("❌ Ошибка отображения процессов")

async def handle_process_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        parts = text.split()
        if len(parts) < 2:
            raise ValueError('Неверный формат команды')
            
        ip = context.user_data.get('selected_pc')
        if not ip:
            raise Exception('Компьютер не выбран')
        
        if parts[-1] == '-n':
            operation = parts[-2]
            name = ' '.join(parts[:-2])
            if not name or operation not in ('kill', 'restart'):
                raise ValueError('Неверный формат команды для управления по имени')
                
            response = requests.post(
                f'http://{ip}:5000/process',
                json={
                    'action': 'manage',
                    'name': name,
                    'operation': operation
                },
                timeout=10
            )
        else:
            pid, operation = parts[:2]
            if not pid.isdigit() or operation not in ('kill', 'restart'):
                raise ValueError('Неверный формат команды для управления по PID')
                
            response = requests.post(
                f'http://{ip}:5000/process',
                json={
                    'action': 'manage',
                    'pid': pid,
                    'operation': operation
                },
                timeout=10
            )
        
        if response.status_code != 200:
            raise Exception('Сервер вернул ошибку')
            
        data = response.json()
        if data.get('status') != 'success':
            raise Exception(data.get('message', 'Неизвестная ошибка'))
        if data['message'] == 'error':
            raise Exception(data.get('message', 'Неизвестная ошибка'))
        if data['message'] == '✅error':
            raise Exception(data.get('message', 'Неизвестная ошибка'))
        
        await update.message.reply_text(f"✅ {data['message']}")
        
    except ValueError as e:
        await update.message.reply_text(
            f'❌ Неверный формат: {str(e)}\n\n'
            'Правильные форматы:\n'
            '1. По PID: "[PID] [действие]"\n'
            '2. По имени: "[имя.exe] [действие] -n"\n\n'
            'Примеры:\n'
            '1234 kill\n'
            'explorer.exe kill -n\n'
            '5678 restart\n'
            'chrome.exe restart -n'
        )
    except Exception as e:
        logger.error(f"Ошибка управления процессом: {e}")
        await update.message.reply_text(f'❌ Ошибка: {str(e)}')
    finally:
        context.user_data['waiting_process_action'] = False

async def cmd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ip = context.user_data.get("selected_pc")
    if not ip:
        await update.message.reply_text("❌ Сначала выберите компьютер с помощью /start")
        return
    
    context.user_data['command_mode'] = True
    await update.message.reply_text(
        "💻 Войдите в режим командной строки. Отправляйте команды одна за другой.\n"
        "Для выхода из режима введите 'exit'.\n\n"
        "Примеры команд:\n"
        "ping google.com\n"
        "ipconfig /all\n"
        "dir C:\\\n"
        "cd C:\\Windows\n"
        "netstat -ano\n\n"
        "Отправьте первую команду:"
    )

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in COMMAND_HISTORY or not COMMAND_HISTORY[user_id]:
        await update.message.reply_text("ℹ История команд пуста")
        return
    
    history = "\n".join([f"{i+1}. {cmd}" for i, cmd in enumerate(COMMAND_HISTORY[user_id][-10:])])
    await update.message.reply_text(f"📜 Последние команды:\n\n{history}")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in ACTIVE_COMMANDS:
        try:
            ACTIVE_COMMANDS[user_id].cancel()
            await update.message.reply_text("🚫 Активная команда была отменена")
        except Exception as e:
            logger.error(f"Ошибка отмены команды: {e}")
            await update.message.reply_text("❌ Не удалось отменить команду")
    else:
        await update.message.reply_text("ℹ Нет активных команд для отмены")

async def stream_command_output(update: Update, context: ContextTypes.DEFAULT_TYPE, ip: str, command: str, message_id: int):
    try:
        ip = context.user_data.get("selected_pc")
        user_id = update.message.from_user.id
        response = requests.post(
            f"http://{ip}:5000/command_stream",
            json={"command": command},
            stream=True,
            timeout=30
        )
        
        full_output = []
        chat_id = update.message.chat_id
        
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data:'):
                    data = json.loads(decoded_line[5:].strip())
                    
                    if 'output' in data:
                        full_output.append(data['output'])
                        if len(full_output) > 20:
                            full_output = full_output[-20:]
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=f"🔄 {command}\n\n" + "\n".join(full_output[-10:])
                        )
                    elif 'error' in data:
                        full_output.append(f"ERROR: {data['error']}")
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=f"❌ {command}\n\n" + "\n".join(full_output[-10:])
                        )
                    elif data.get('status') == 'completed':
                        ip = context.user_data.get("selected_pc")

                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=f"✅ {command}\n\n" + "\n".join(full_output[-10:]) + f"\n\nКод завершения: {data['exit_code']}"
                        )
                        break
        
        if user_id in ACTIVE_COMMANDS:
            del ACTIVE_COMMANDS[user_id]
        
    except asyncio.CancelledError:
        logger.info(f"Команда {command} была отменена")
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=message_id,
            text=f"🚫 Команда отменена: {command}"
        )
    except Exception as e:
        logger.error(f"Ошибка потокового вывода: {e}")
        ip = context.user_data.get("selected_pc")
        
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=message_id,
            text=f"❌ Ошибка при выполнении команды: {str(e)}"
        )
        if user_id in ACTIVE_COMMANDS:
            del ACTIVE_COMMANDS[user_id]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        
        if context.user_data.get('waiting_process_action'):
            await handle_process_action(update, context)
        elif context.user_data.get('waiting_new_process'):
            ip = context.user_data.get("selected_pc")
            if not ip:
                await update.message.reply_text("❌ Компьютер не выбран!")
                return
            
            command_text = update.message.text.strip()
            # Проверяем, есть ли в конце цифра (количество повторений)
            import re
            match = re.search(r'^(.*)\s+(\d+)$', command_text)
            
            if match:
                # Извлекаем команду и количество повторений
                base_command = match.group(1).strip()
                count = int(match.group(2))
                
                # Ограничиваем количество повторений для безопасности
                if count > 100:
                    await update.message.reply_text("❌ Максимальное количество запусков - 100")
                    context.user_data["waiting_new_process"] = False
                    return
                
                if count <= 0:
                    await update.message.reply_text("❌ Количество должно быть положительным числом")
                    context.user_data["waiting_new_process"] = False
                    return
                
                # Запускаем процесс несколько раз
                success_count = 0
                for i in range(count):
                    try:
                        response = requests.post(
                            f"http://{ip}:5000/command",
                            json={"command": f"start {base_command}"},
                            timeout=10
                        )
                        # Проверяем успешность каждого запроса
                        if response.status_code == 200:
                            success_count += 1
                    except Exception as e:
                        logger.error(f"Ошибка запуска процесса (попытка {i+1}): {e}")
                        # Продолжаем с другими попытками
                
                await update.message.reply_text(f"✅ Запущено {success_count} из {count} процессов: {base_command}")
            else:
                # Обычный запуск одного процесса
                try:
                    response = requests.post(
                        f"http://{ip}:5000/command",
                        json={"command": f"start {command_text}"},
                        timeout=10
                    )
                    await update.message.reply_text(response.json().get("status", "Процесс запущен"))
                except Exception as e:
                    logger.error(f"Ошибка запуска процесса: {e}")
                    await update.message.reply_text("❌ Не удалось запустить процесс")
            
            context.user_data["waiting_new_process"] = False

        elif context.user_data.get('command_mode', False):
            command = update.message.text.strip()
            if command.lower() == 'exit':
                context.user_data['command_mode'] = False
                await update.message.reply_text("🚪 Режим команд завершен. Для повторного входа используйте /cmd")
                return
            
            ip = context.user_data.get("selected_pc")
            if not ip:
                await update.message.reply_text("❌ Компьютер не выбран!")
                return
            
            if user_id not in COMMAND_HISTORY:
                COMMAND_HISTORY[user_id] = []
            COMMAND_HISTORY[user_id].append(command)
            
            msg = await update.message.reply_text(f"⏳ Выполнение: {command}")
            
            try:
                # Обработка команды cd отдельно
                if command.startswith('cd '):
                    dir_name = command[3:].strip()
                    response = requests.post(
                        f"http://{ip}:5000/command",
                        json={"command": f"explorer list {dir_name}"},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "success":
                            context.user_data["current_path"] = data.get("current_path", dir_name)
                            await msg.edit_text(f"✅ Перешёл в директорию: {dir_name}")
                        else:
                            await msg.edit_text(f"❌ Ошибка: {data.get('message', 'Не удалось сменить директорию')}")
                    else:
                        await msg.edit_text("❌ Не удалось сменить директорию")
                # Обработка длительных команд с потоковым выводом
                elif command.startswith(('ping', 'tracert', 'nslookup', 'netstat')):
                    stream_task = asyncio.create_task(
                        stream_command_output(update, context, ip, command, msg.message_id)
                    )
                    ACTIVE_COMMANDS[user_id] = stream_task
                # Обработка обычных команд
                else:
                    response = requests.post(
                        f"http://{ip}:5000/command",
                        json={"command": command},
                        timeout=30
                    )
                    result = response.json().get("output", response.json().get("status", "Команда выполнена"))
                    await msg.edit_text(f"✅ {command}\n\n{result}")
            except Exception as e:
                await msg.edit_text(f"❌ Ошибка выполнения команды: {str(e)}")
        else:
            await update.message.reply_text("ℹ Введите команду или выберите действие из меню")
    
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке сообщения")

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    computers = load_computers()
    
    try:
        if data.startswith("select_"):
            computer_name = data[7:]
            if computer_name in computers:
                ip = computers[computer_name]
                is_online = await check_computer_status(ip)
                
                if not is_online:
                    await query.edit_message_text(f"❌ Компьютер {computer_name} сейчас оффлайн")
                    return
                    
                context.user_data["selected_pc"] = ip
                context.user_data["computer_name"] = computer_name
                
                keyboard = [
                    [InlineKeyboardButton("📸 Скриншот", callback_data="screenshot"),
                     InlineKeyboardButton("📊 Процессы", callback_data="processes")],
                    # [InlineKeyboardButton("📂 Проводник", callback_data="explorer")],
                    [InlineKeyboardButton("🔌 Выключить", callback_data="shutdown"),
                     InlineKeyboardButton("🔄 Перезагрузить", callback_data="restart")],
                    [InlineKeyboardButton("🔒 Заблокировать", callback_data="lock"),
                     InlineKeyboardButton("🖥 Выключить экран", callback_data="screen_off")],
                    [InlineKeyboardButton("💻 Включить экран", callback_data="screen_on")],
                    [InlineKeyboardButton("➕ Запустить процесс", callback_data="start_process")],
                    [InlineKeyboardButton("🔒 Запустить winlocker", callback_data="run_winlocker")],
                    [InlineKeyboardButton("🔓 Остановить winlocker", callback_data="stop_winlocker")],
                    [InlineKeyboardButton("💻 Командный режим", callback_data="cmd_mode")],
                    [InlineKeyboardButton("📜 История команд", callback_data="show_history")],
                    [InlineKeyboardButton("🖱 Управление", callback_data="control_menu")],
                    # [InlineKeyboardButton("🔄 Проверить статус", callback_data=f"select_{computer_name}")]
                    [InlineKeyboardButton("❌Меню выбора компьтера", callback_data=f"load_computers")]
                ]
                await query.edit_message_text(
                    text=f"Управление компьютером: {computer_name} (🟢 Онлайн)",
                    reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif data == "processes":
            await show_processes(query, context)
        
        elif data in ("next_processes", "prev_processes"):
            await handle_process_pagination(update, context)
        
        elif data == "start_process":
            context.user_data["waiting_new_process"] = True
            await query.edit_message_text("Введите команду для запуска нового процесса:")

                    
        elif data == "load_computers":
            try:
                computers = load_computers()
                if not computers:
                    await query.edit_message_text("🔍 Нет доступных компьютеров")
                    return

                status_messages = []
                for name, ip in computers.items():
                    is_online = await check_computer_status(ip)
                    status = "🟢 Онлайн" if is_online else "🔴 Оффлайн"
                    status_messages.append(f"{name} ({ip}) - {status}")

                # Обновляем текст сообщения и клавиатуру
                await query.edit_message_text(
                    "📊 Статус компьютеров:\n" + "\n".join(status_messages)
                )

                keyboard = [
                    [InlineKeyboardButton(f"{name} ({ip})", callback_data=f"select_{name}")]
                    for name, ip in computers.items()
                ]
                await query.message.reply_text( # Отправляем новое сообщение с клавиатурой
                    "🖥 Выберите компьютер:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                # Очищаем выбор компьютера в контексте, так как мы возвращаемся к выбору
                context.user_data.pop("selected_pc", None)
                context.user_data.pop("computer_name", None)

            except Exception as e:
                logger.error(f"Ошибка загрузки меню выбора компьютеров: {e}")
                await query.edit_message_text("❌ Произошла ошибка при загрузке меню")
       
       

        elif data == "control_menu":
            keyboard = [
                [InlineKeyboardButton("🖱 Мышь", callback_data="control_mouse")],
                [InlineKeyboardButton("⌨ Клавиатура", callback_data="control_keyboard")]
            ]
            await query.edit_message_text(
                text="Выберите, чем хотите управлять:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == "control_mouse":
            keyboard = [
                [InlineKeyboardButton("⬅ Назад", callback_data="control_menu")],
                [InlineKeyboardButton("🖱 ЛКМ", callback_data="mouse_click_left")],
                [InlineKeyboardButton("🖱 ПКМ", callback_data="mouse_click_right")]
            ]
            await query.edit_message_text(
                text="🖱 Управление мышью:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data in ("mouse_click_left", "mouse_click_right"):
            ip = context.user_data.get("selected_pc")
            if not ip:
                await query.edit_message_text("❌ Компьютер не выбран!")
                return
            try:
                # Определяем команду для сервера
                mouse_command = "mouse_left_click" if data == "mouse_click_left" else "mouse_right_click"
                
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": mouse_command},
                    timeout=10
                )
                result_text = response.json().get("status", "Команда выполнена")
                await query.edit_message_text(f"✅ {result_text}")
                # После выполнения команды возвращаемся в меню мыши
                # Можно добавить автоматический возврат или кнопку "Назад"
                keyboard = [
                    [InlineKeyboardButton("⬅ Назад", callback_data="control_menu")],
                    [InlineKeyboardButton("🖱 ЛКМ", callback_data="mouse_click_left")],
                    [InlineKeyboardButton("🖱 ПКМ", callback_data="mouse_click_right")]
                ]
                await query.message.reply_text( # Отправляем новое сообщение с меню мыши
                    text="🖱 Управление мышью:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Ошибка отправки команды мыши: {e}")
                await query.edit_message_text("❌ Не удалось подключиться к компьютеру")

        elif data == "control_keyboard":
            keyboard = [
                [InlineKeyboardButton("⬅ Назад", callback_data="control_menu")],
                [InlineKeyboardButton("↲ Enter", callback_data="key_enter")],
                [InlineKeyboardButton("⌫ Backspace", callback_data="key_backspace")],
                [InlineKeyboardButton("↹ Tab", callback_data="key_tab")],
                [InlineKeyboardButton(" Esc", callback_data="key_escape")],
                [InlineKeyboardButton("↑", callback_data="key_up")],
                [InlineKeyboardButton("←", callback_data="key_left"), InlineKeyboardButton("↓", callback_data="key_down"), InlineKeyboardButton("→", callback_data="key_right")],
                [InlineKeyboardButton("Ctrl+C", callback_data="key_ctrl_c"), InlineKeyboardButton("Ctrl+V", callback_data="key_ctrl_v")],
                [InlineKeyboardButton("Ctrl+A", callback_data="key_ctrl_a"), InlineKeyboardButton("Ctrl+Z", callback_data="key_ctrl_z")],
                [InlineKeyboardButton("Alt+Tab", callback_data="key_alt_tab")],
                [InlineKeyboardButton(" Windows", callback_data="key_win")]
            ]
            await query.edit_message_text(
                text="⌨ Управление клавиатурой:")
            
        
        elif data == "cmd_mode":
            ip = context.user_data.get("selected_pc")
            if not ip:
                await query.edit_message_text("❌ Компьютер не выбран!")
                return
            
            context.user_data['command_mode'] = True
            await query.edit_message_text(
                "💻 Войдите в режим командной строки. Отправляйте команды одна за другой.\n"
                "Для выхода из режима введите 'exit'.\n\n"
                "Примеры команд:\n"
                "ping google.com\n"
                "ipconfig /all\n"
                "dir C:\\\n"
                "cd C:\\Windows\n"
                "netstat -ano\n\n"
                "Отправьте первую команду:"
            )
        
        elif data == "show_history":
            user_id = query.from_user.id
            if user_id not in COMMAND_HISTORY or not COMMAND_HISTORY[user_id]:
                await query.edit_message_text("ℹ История команд пуста")
                return
            
            history = "\n".join([f"{i+1}. {cmd}" for i, cmd in enumerate(COMMAND_HISTORY[user_id][-10:])])
            await query.edit_message_text(f"📜 Последние команды:\n\n{history}")
        
        elif data == "run_winlocker":
            ip = context.user_data.get("selected_pc")
            if not ip:
                await query.edit_message_text("❌ Компьютер не выбран!")
                return
            
            try:
                ip = context.user_data.get("selected_pc")

                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": "start_winlocker"},
                    timeout=10
                )
                await query.edit_message_text(f"✅ {response.json().get('status', 'winlocker запущен')}")
            except Exception as e:
                logger.error(f"Ошибка запуска winlocker: {e}")
                await query.edit_message_text("❌ Не удалось запустить winlocker")

        elif data == "stop_winlocker":
            ip = context.user_data.get("selected_pc")
            if not ip:
                await query.edit_message_text("❌ Компьютер не выбран!")
                return
            
            try:
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": "stop_winlocker"},
                    timeout=10
                )
                await query.edit_message_text(f"✅ {response.json().get('status', 'winlocker остановлен')}")
            except Exception as e:
                logger.error(f"Ошибка остановки winlocker: {e}")
                await query.edit_message_text("❌ Не удалось остановить winlocker")

        elif data == "explorer":
            ip = context.user_data.get("selected_pc")
            if not ip:
                await query.edit_message_text("❌ Компьютер не выбран!")
                return
            
            try:
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": "explorer list"},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        files = data.get("files", [])
                        dirs = data.get("directories", [])
                        drive_info = data.get("drive_info", {})
                        
                        message = "📂 Содержимое текущей директории:\n\n"
                        if drive_info:
                            message += f"💽 Диск {drive_info.get('drive', '')} ({drive_info.get('label', '')})\n"
                            message += f"🔢 Серийный номер: {drive_info.get('serial', '')}\n\n"
                        
                        message += "📁 Папки:\n" + "\n".join([f"- {d}" for d in dirs]) + "\n\n"
                        message += "📄 Файлы:\n" + "\n".join([f"- {f}" for f in files])
                        
                        keyboard = [
                            [InlineKeyboardButton("⬆ На уровень выше", callback_data="explorer_up")],
                            [InlineKeyboardButton("🔄 Обновить", callback_data="explorer_refresh")]
                        ]
                        
                        for d in dirs:
                            keyboard.append([InlineKeyboardButton(f"📁 {d}", callback_data=f"explorer_dir_{d}")])
                        
                        context.user_data["current_path"] = data.get("current_path", "")
                        
                        await query.edit_message_text(
                            text=message,
                            reply_markup=InlineKeyboardMarkup(keyboard))
                    else:
                        await query.edit_message_text(f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}")
                else:
                    await query.edit_message_text("❌ Не удалось подключиться к компьютеру")
            
            except Exception as e:
                logger.error(f"Ошибка получения списка файлов: {e}")
                await query.edit_message_text(f"❌ Ошибка: {str(e)}")
        
        elif data.startswith("explorer_dir_"):
            ip = context.user_data.get("selected_pc")

            directory = data[13:]
            current_path = context.user_data.get("current_path", "")
            new_path = os.path.join(current_path, directory)
            
            try:
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": f"explorer list {new_path}"},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        files = data.get("files", [])
                        dirs = data.get("directories", [])
                        drive_info = data.get("drive_info", {})
                        
                        message = f"📂 Содержимое папки: {new_path}\n\n"
                        if drive_info:
                            message += f"💽 Диск {drive_info.get('drive', '')} ({drive_info.get('label', '')})\n\n"
                        
                        message += "📁 Папки:\n" + "\n".join([f"- {d}" for d in dirs]) + "\n\n"
                        message += "📄 Файлы:\n" + "\n".join([f"- {f}" for f in files])
                        
                        keyboard = [
                            [InlineKeyboardButton("⬆ На уровень выше", callback_data="explorer_up")],
                            [InlineKeyboardButton("🔄 Обновить", callback_data="explorer_refresh")]
                        ]
                        
                        for d in dirs:
                            keyboard.append([InlineKeyboardButton(f"📁 {d}", callback_data=f"explorer_dir_{d}")])
                        
                        for f in files:
                            keyboard.append([InlineKeyboardButton(f"📄 {f}", callback_data=f"explorer_file_{f}")])
                        
                        context.user_data["current_path"] = new_path
                        
                        await query.edit_message_text(
                            text=message,
                            reply_markup=InlineKeyboardMarkup(keyboard))
                    else:
                        await query.edit_message_text(f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}")
                else:
                    await query.edit_message_text("❌ Не удалось подключиться к компьютеру")
            
            except Exception as e:
                logger.error(f"Ошибка навигации по папкам: {e}")
                await query.edit_message_text(f"❌ Ошибка: {str(e)}")
        
        elif data == "explorer_up":
            ip = context.user_data.get("selected_pc")

            current_path = context.user_data.get("current_path", "")
            if current_path:
                parent_path = os.path.dirname(current_path)
                ip = context.user_data.get("selected_pc")
                
                try:
                    response = requests.post(
                        f"http://{ip}:5000/command",
                        json={"command": f"explorer list {parent_path}"},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "success":
                            files = data.get("files", [])
                            dirs = data.get("directories", [])
                            drive_info = data.get("drive_info", {})
                            
                            message = f"📂 Содержимое папки: {parent_path}\n\n"
                            if drive_info:
                                message += f"💽 Диск {drive_info.get('drive', '')} ({drive_info.get('label', '')})\n\n"
                            
                            message += "📁 Папки:\n" + "\n".join([f"- {d}" for d in dirs]) + "\n\n"
                            message += "📄 Файлы:\n" + "\n".join([f"- {f}" for f in files])
                            
                            keyboard = []
                            if parent_path:
                                keyboard.append([InlineKeyboardButton("⬆ На уровень выше", callback_data="explorer_up")])
                            keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="explorer_refresh")])
                            
                            for d in dirs:
                                keyboard.append([InlineKeyboardButton(f"📁 {d}", callback_data=f"explorer_dir_{d}")])
                            
                            for f in files:
                                keyboard.append([InlineKeyboardButton(f"📄 {f}", callback_data=f"explorer_file_{f}")])
                            
                            context.user_data["current_path"] = parent_path
                            
                            await query.edit_message_text(
                                text=message,
                                reply_markup=InlineKeyboardMarkup(keyboard))
                        else:
                            await query.edit_message_text(f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}")
                    else:
                        await query.edit_message_text("❌ Не удалось подключиться к компьютеру")
                
                except Exception as e:
                    logger.error(f"Ошибка перехода на уровень выше: {e}")
                    await query.edit_message_text(f"❌ Ошибка: {str(e)}")
        
        elif data == "explorer_refresh":
            current_path = context.user_data.get("current_path", "")
            command = "explorer list" if not current_path else f"explorer list {current_path}"
            
            try:
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": command},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        files = data.get("files", [])
                        dirs = data.get("directories", [])
                        drive_info = data.get("drive_info", {})
                        
                        message = f"📂 Содержимое папки: {current_path if current_path else 'корневая'}\n\n"
                        if drive_info:
                            message += f"💽 Диск {drive_info.get('drive', '')} ({drive_info.get('label', '')})\n\n"
                        
                        message += "📁 Папки:\n" + "\n".join([f"- {d}" for d in dirs]) + "\n\n"
                        message += "📄 Файлы:\n" + "\n".join([f"- {f}" for f in files])
                        
                        keyboard = []
                        if current_path:
                            keyboard.append([InlineKeyboardButton("⬆ На уровень выше", callback_data="explorer_up")])
                        keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="explorer_refresh")])
                        
                        for d in dirs:
                            keyboard.append([InlineKeyboardButton(f"📁 {d}", callback_data=f"explorer_dir_{d}")])
                        
                        for f in files:
                            keyboard.append([InlineKeyboardButton(f"📄 {f}", callback_data=f"explorer_file_{f}")])
                        
                        await query.edit_message_text(
                            text=message,
                            reply_markup=InlineKeyboardMarkup(keyboard))
                    else:
                        ip = context.user_data.get("selected_pc")

                        await query.edit_message_text(f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}")
                else:
                    await query.edit_message_text("❌ Не удалось подключиться к компьютеру")
            
            except Exception as e:
                logger.error(f"Ошибка обновления списка файлов: {e}")
                await query.edit_message_text(f"❌ Ошибка: {str(e)}")
        
        elif data.startswith("explorer_file_"):
            filename = data[14:]
            current_path = context.user_data.get("current_path", "")
            filepath = os.path.join(current_path, filename)
            
            keyboard = [
                [InlineKeyboardButton("⬇ Скачать", callback_data=f"download_{filepath}")],
                [InlineKeyboardButton("❌ Удалить", callback_data=f"delete_{filepath}")],
                [InlineKeyboardButton("🔙 Назад", callback_data="explorer_back")]
            ]
            
            await query.edit_message_text(
                text=f"Файл: {filename}\nПуть: {filepath}",
                reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif data == "explorer_back":
            ip = context.user_data.get("selected_pc")
            
            current_path = context.user_data.get("current_path", "")
            command = "explorer list" if not current_path else f"explorer list {current_path}"
            
            try:
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": command},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        files = data.get("files", [])
                        dirs = data.get("directories", [])
                        drive_info = data.get("drive_info", {})
                        
                        message = f"📂 Содержимое папки: {current_path if current_path else 'корневая'}\n\n"
                        if drive_info:
                            message += f"💽 Диск {drive_info.get('drive', '')} ({drive_info.get('label', '')})\n\n"
                        
                        message += "📁 Папки:\n" + "\n".join([f"- {d}" for d in dirs]) + "\n\n"
                        message += "📄 Файлы:\n" + "\n".join([f"- {f}" for f in files])
                        
                        keyboard = []
                        if current_path:
                            keyboard.append([InlineKeyboardButton("⬆ На уровень выше", callback_data="explorer_up")])
                        keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="explorer_refresh")])
                        
                        for d in dirs:
                            keyboard.append([InlineKeyboardButton(f"📁 {d}", callback_data=f"explorer_dir_{d}")])
                        
                        for f in files:
                            keyboard.append([InlineKeyboardButton(f"📄 {f}", callback_data=f"explorer_file_{f}")])
                        
                        ip = context.user_data.get("selected_pc")
                        await query.edit_message_text(
                            text=message,
                            reply_markup=InlineKeyboardMarkup(keyboard))
                    else:
                        await query.edit_message_text(f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}")
                else:
                    await query.edit_message_text("❌ Не удалось подключиться к компьютеру или другая ошибка прноверьте на компьютере")
            
            except Exception as e:
                logger.error(f"Ошибка возврата к списку файлов: {e}")
                await query.edit_message_text(f"❌ Ошибка: {str(e)}")
        
        elif data.startswith("download_"):
            filepath = data[9:]
            ip = context.user_data.get("selected_pc")

            try:
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": f"explorer download {filepath}"},
                    stream=True,
                    timeout=30
                )
                
                if response.status_code == 200:
                    filename = os.path.basename(filepath)
                    temp_file = os.path.join(TEMP_DIR, filename)
                    
                    with open(temp_file, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    await query.message.reply_document(
                        document=open(temp_file, "rb"),
                        caption=f"Файл: {filename}"
                    )
                    
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                else:
                    await query.edit_message_text("❌ Не удалось скачать файл")
            
            except Exception as e:
                logger.error(f"Ошибка скачивания файла: {e}")
                await query.edit_message_text(f"❌ Ошибка скачивания: {str(e)}")
        
        elif data.startswith("delete_"):
            filepath = data[7:]
            try:
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": f"explorer delete {filepath}"},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        await query.edit_message_text(f"✅ Файл удален: {filepath}")
                    else:
                        await query.edit_message_text(f"❌ Ошибка: {data.get('message', 'Не удалось удалить файл')}")
                else:
                    await query.edit_message_text("❌ Не удалось удалить файл")
            
            except Exception as e:
                logger.error(f"Ошибка удаления файла: {e}")
                await query.edit_message_text(f"❌ Ошибка удаления: {str(e)}")
        
        elif data == "screenshot":
            ip = context.user_data.get("selected_pc")
            if not ip:
                await query.edit_message_text("❌ Компьютер не выбран!")
                return
            
            message = await query.message.reply_text("🔄 Делаем скриншот... (это может занять до 30 секунд)")
            
            try:
                response = requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": "screenshot"},
                    timeout=30
                )
                
                if response.status_code == 200:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_file = os.path.join(TEMP_DIR, f"temp_screenshot_{timestamp}.png")
                    
                    try:
                        with open(temp_file, "wb") as f:
                            f.write(response.content)
                        
                        if os.path.getsize(temp_file) == 0:
                            raise Exception("Получен пустой файл скриншота")
                            
                        await query.message.reply_photo(
                            photo=open(temp_file, "rb"),
                            caption=f"Скриншот с {context.user_data.get('computer_name', ip)}"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка обработки скриншота: {e}")
                        await query.edit_message_text(f"❌ Ошибка обработки скриншота: {e}")
                    finally:
                        ip = context.user_data.get("selected_pc")

                        if os.path.exists(temp_file):
                            try:
                                os.remove(temp_file)
                            except Exception as e:
                                logger.error(f"Ошибка удаления временного файла: {e}")
                    
                    await message.delete()
                else:
                    error_msg = response.json().get("status", "Неизвестная ошибка сервера")
                    logger.error(f"Ошибка сервера при получении скриншота: {error_msg}")
                    await message.edit_text(f"❌ Ошибка сервера: {error_msg}")
                    
            except requests.exceptions.Timeout:
                logger.error("Таймаут при получении скриншота")
                await message.edit_text("⌛ Превышено время ожидания скриншота")
            except Exception as e:
                logger.error(f"Неожиданная ошибка при получении скриншота: {e}")
                await message.edit_text(f"❌ Неожиданная ошибка: {str(e)}")
        
        else:
            ip = context.user_data.get("selected_pc")
            if not ip:
                await query.edit_message_text("❌ Компьютер не выбран!")
                return
            
            try:
                requests.post(
                    f"http://{ip}:5000/command",
                    json={"command": data},
                    timeout=10
                )
                await query.edit_message_text(f"✅ Команда {data} отправлена")
            except Exception as e:
                logger.error(f"Ошибка отправки команды: {e}")
                await query.edit_message_text("❌ Не удалось подключиться к компьютеру")
    
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await query.edit_message_text("❌ Произошла ошибка при обработке команды")

async def post_init(application):
    """Функция для пост-инициализации"""
    await application.bot.set_my_commands([
        ("start", "Запустить бота"),
        ("cmd", "Войти в режим командной строки"),
        ("history", "Показать историю команд"),
        ("cancel", "Отменить текущую команду")
    ])
    
    logger.info("Бот успешно запущен")

def main():
    if "YOUR_TELEGRAM_BOT_TOKEN" in BOT_TOKEN:
        print("ОШИБКА: Замените BOT_TOKEN на реальный токен!")
        print("Получите токен у @BotFather в Telegram")
        return
    
    try:
        application = ApplicationBuilder() \
            .token(BOT_TOKEN) \
            .post_init(post_init) \
            .build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("cmd", cmd_command))
        application.add_handler(CommandHandler("history", history_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(CallbackQueryHandler(handle_button_click))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Запуск бота в режиме polling...")
        application.run_polling(
            poll_interval=3.0,
            timeout=30,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        import time
        time.sleep(5)
        main()

if __name__ == '__main__':
    main()