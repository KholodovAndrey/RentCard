import os
import json
import re
import logging
import asyncio
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from io import BytesIO
from datetime import datetime
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.units import cm
from reportlab.lib import colors
from aiogram import Bot, Dispatcher, types, F
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram_calendar.schemas import SimpleCalendarCallback
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Путь к директории, где лежит main.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIGS_DIR = os.path.join(BASE_DIR, 'configs')
PHOTOS_DIR = os.path.join(BASE_DIR, 'photos')
FONTS_DIR = BASE_DIR

font_path = os.path.join(FONTS_DIR, 'DejaVuSans.ttf')
bold_font_path = os.path.join(FONTS_DIR, 'DejaVuSans-Bold.ttf')

try:
    pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', bold_font_path))
    font_normal = 'DejaVuSans'
    font_bold = 'DejaVuSans-Bold'
except Exception as e:
    print(f"Ошибка загрузки шрифтов: {e}")
    font_normal = 'Helvetica'
    font_bold = 'Helvetica-Bold'

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Загрузка данных о катерах
with open(os.path.join(BASE_DIR, 'configs', 'boats.json'), 'r', encoding='utf-8') as f:
    BOATS = json.load(f)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class Form(StatesGroup):
    boat = State()         # Выбор лодки (автоматически заполняет pier, captain_name, captain_phone)
    hours = State()        # Часы аренды
    date = State()         # Дата
    time_hour = State()    # Час отправления
    time_minute = State()  # Минуты
    time = State()         # Ручной ввод времени
    guests_count = State() # Количество гостей (переходим сразу после времени)
    captain_choice = State()
    client_name = State()  # Имя клиента
    remaining_payment = State()  # Остаток оплаты

RULES = [
    "• Напитки и закуски — на ваше усмотрение, на борту есть изящные бокалы.",
    "• Исключите продукты, способные оставить пятна: красное вино, вишнёвый сок, яркие ягоды.",
    "• Курение возможно только по согласованию с капитаном.",
    "• Пиротехника и открытый огонь запрещены.",
    "• Обувь — тонкие каблуки и шпильки могут повредить покрытие палубы.",
    "• Прибытие — рекомендуем быть у причала за 10 минут до отправления."
]

MANAGER_INFO = [
    "Номер капитана используется только за 5-10 минут до рейса.",
    "Ваш менеджер: Александра +7 921-927-21-13"
]

async def is_admin(user_id: int) -> bool:
    return True #user_id == ADMIN_ID

def get_boat_select_button(boat_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"✅ Выбрать {boat_name}", 
        callback_data=f"boat_{boat_name}"
    )
    builder.button(
        text="⬅️ Назад", 
        callback_data="back_to_boats"
    )
    builder.adjust(1)  # Располагаем кнопки вертикально
    return builder.as_markup()

def get_hours_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    hours = ['1', '1.5', '2', '2.5', '3', '4', '5', '6']
    for hour in hours:
        builder.add(KeyboardButton(text=hour))
    builder.adjust(4, 4)  # 4 кнопки в первом ряду, 4 во втором
    return builder.as_markup(resize_keyboard=True)

def round_corners(image_path, radius=20):
    """Создает изображение с закругленными углами"""
    from PIL import Image, ImageDraw
    from io import BytesIO
    
    original = Image.open(image_path).convert("RGBA")
    width, height = original.size
    
    # Создаем маску с закругленными углами
    mask = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, width, height), radius, fill=255)
    
    # Применяем маску к изображению
    result = Image.new('RGBA', (width, height))
    result.paste(original, (0, 0), mask)
    
    # Сохраняем во временный буфер
    output = BytesIO()
    result.save(output, format='PNG')
    output.seek(0)
    return output

def add_image_to_pdf(canvas, image_path, x, y, width, height, radius=15):
    """Добавляет изображение на PDF canvas с закругленными углами"""
    from reportlab.lib.utils import ImageReader
    
    try:
        # Обрабатываем изображение с закругленными углами
        rounded_img = round_corners(image_path, radius)
        
        # Рисуем обработанное изображение
        img = ImageReader(rounded_img)
        canvas.drawImage(img, x, y, width=width, height=height, mask='auto')
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении изображения: {e}")
        # Если возникла ошибка, рисуем обычное изображение
        img = ImageReader(image_path)
        canvas.drawImage(img, x, y, width=width, height=height)

def fill_pdf_template(data: dict) -> str:
    """Заполняет шаблон PDF данными из аренды"""
    boat_data = BOATS[data['boat']]
    
    # Пути к файлам
    template_path = os.path.join(CONFIGS_DIR, 'form.pdf')
    boat_image_path = os.path.join(PHOTOS_DIR, boat_data['photo'])
    output_path = os.path.join(BASE_DIR, 'аренда.pdf')
    
    # Создаем временный PDF
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    
    # Устанавливаем белый цвет текста
    can.setFillColor(colors.white)
    
    # Устанавливаем шрифт
    try:
        can.setFont('DejaVuSans', 12)
    except:
        can.setFont('Helvetica', 12)
    
    # Добавляем изображение лодки
    add_image_to_pdf(can, boat_image_path, x=19, y=460, width=558, height=372, radius=30)
    
    # Подготавливаем данные для заполнения
    fields = {
        'Дата и время': f"{data['date']} в {data['time']}",
        'Название катера': data['boat'],
        'Остаток к оплате': f"{data.get('remaining_payment', '0')} руб.",
        'Продолжительность': f"{data['hours']} ч.",
        'ФИО гостя': data['client_name'],
        'Количество гостей': data['guests_count'],
        'Имя капитана': data['captain_name'],
        'Телефон капитана': data['captain_phone'],
        'Причал': data['pier']
    }
    
    # Координаты полей (x, y)
    coordinates = {
        'Дата и время': (22, 370),
        'Название катера': (22, 315),
        'Остаток к оплате': (22, 260),
        'Продолжительность': (429, 370),
        'ФИО гостя': (429, 315),
        'Количество гостей': (429, 260),
        'Имя капитана': (208, 315),
        'Телефон капитана': (208, 260),
        'Причал': (208, 370)
    }
    
    # Заполняем текстовые поля
    for field, value in fields.items():
        if field in coordinates:
            x, y = coordinates[field]
            can.drawString(x, y, value)
    
    can.save()
    packet.seek(0)
    new_pdf = PdfReader(packet)
    
    # Объединяем с шаблоном
    existing_pdf = PdfReader(open(template_path, "rb"))
    output = PdfWriter()
    page = existing_pdf.pages[0]
    page.merge_page(new_pdf.pages[0])
    output.add_page(page)
    
    # Сохраняем результат
    with open(output_path, "wb") as output_stream:
        output.write(output_stream)
    
    return output_path

def generate_hours_keyboard():
    builder = InlineKeyboardBuilder()
    # Добавляем кнопки с часами с 9 утра до 11 вечера
    for hour in range(9, 23):
        builder.button(text=f"{hour}:00", callback_data=f"hour_{hour}")
    builder.adjust(4)  # 4 кнопки в ряд
    return builder.as_markup()

def generate_minutes_keyboard(hour: int):
    builder = InlineKeyboardBuilder()
    # Добавляем кнопки с минутами
    for minute in ['00', '15', '30', '45']:
        builder.button(text=f"{hour}:{minute}", callback_data=f"minute_{hour}:{minute}")
    builder.adjust(2)  # 2 кнопки в ряд
    return builder.as_markup()

# Вспомогательные функции должны быть определены ДО их использования
async def ask_hours(message: types.Message, state: FSMContext):
    """Запрос количества часов аренды"""
    await message.answer("Сколько часов аренды?", reply_markup=get_hours_keyboard())
    await state.set_state(Form.hours)

async def ask_captain_choice(message: types.Message, captains: list):
    """Запрос выбора капитана"""
    builder = InlineKeyboardBuilder()
    for idx, captain in enumerate(captains):
        builder.button(
            text=f"{captain['name']} ({captain['phone']})",
            callback_data=f"capt_{idx}"
        )
    builder.adjust(1)
    await message.answer("👨‍✈️ Выберите капитана:", reply_markup=builder.as_markup())
    
@dp.message(Command("start"))
async def start(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    # Создаем инлайн клавиатуру с кнопками лодок
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Сортируем названия лодок по алфавиту
    sorted_boat_names = sorted(BOATS.keys())
    
    # Создаем кнопки в 3 столбца
    buttons = []
    for i in range(0, len(sorted_boat_names), 3):  # Меняем шаг на 3
        row = []
        
        # Добавляем до 3 кнопок в строку
        for j in range(3):
            if i + j < len(sorted_boat_names):
                boat_name = sorted_boat_names[i + j]
                row.append(InlineKeyboardButton(
                    text=boat_name,
                    callback_data=f"boat_select:{boat_name}"
                ))
        
        buttons.append(row)
    
    keyboard.inline_keyboard = buttons
    
    await message.answer(
        "🚤 Выберите катер:",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "cancel_boat_selection", Form.captain_choice)
async def cancel_captain_selection(callback: types.CallbackQuery, state: FSMContext):
    # Очищаем состояние
    await state.clear()
    
    # Создаем инлайн клавиатуру с кнопками лодок
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Сортируем названия лодок по алфавиту
    sorted_boat_names = sorted(BOATS.keys())
    
    # Создаем кнопки в 3 столбца
    buttons = []
    for i in range(0, len(sorted_boat_names), 3):
        row = []
        
        # Добавляем до 3 кнопок в строку
        for j in range(3):
            if i + j < len(sorted_boat_names):
                boat_name = sorted_boat_names[i + j]
                row.append(InlineKeyboardButton(
                    text=boat_name,
                    callback_data=f"boat_select:{boat_name}"
                ))
        
        buttons.append(row)
    
    keyboard.inline_keyboard = buttons
    
    # Редактируем сообщение с возвратом к выбору катера
    await callback.message.edit_text(
        "🚤 Выберите катер:",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_boats")
async def back_to_boats_list(callback: types.CallbackQuery, state: FSMContext):
    # Очищаем состояние
    await state.clear()
    
    # Создаем инлайн клавиатуру с кнопками лодок
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Сортируем названия лодок по алфавиту
    sorted_boat_names = sorted(BOATS.keys())
    
    # Создаем кнопки в 3 столбца
    buttons = []
    for i in range(0, len(sorted_boat_names), 3):
        row = []
        
        # Добавляем до 3 кнопок в строку
        for j in range(3):
            if i + j < len(sorted_boat_names):
                boat_name = sorted_boat_names[i + j]
                row.append(InlineKeyboardButton(
                    text=boat_name,
                    callback_data=f"boat_select:{boat_name}"
                ))
        
        buttons.append(row)
    
    keyboard.inline_keyboard = buttons
    
    # Отправляем новое сообщение со списком катеров
    await callback.message.answer(
        "🚤 Выберите катер:",
        reply_markup=keyboard
    )
    await callback.answer()

# Обработчик выбора лодки
@dp.callback_query(lambda c: c.data.startswith("boat_select:"))
async def process_boat_selection(callback_query: types.CallbackQuery):
    boat_name = callback_query.data.split(":")[1]
    
    if boat_name not in BOATS:
        await callback_query.answer("Катер не найден")
        return
    
    boat_data = BOATS[boat_name]
    
    try:
        photo_path = os.path.join(PHOTOS_DIR, boat_data['photo'])
        caption = f"🚤 {boat_name}\n📍 Причал: {boat_data['pier']}"
        
        # Добавляем первого капитана в описание
        if boat_data['captain']:
            captain = boat_data['captain'][0]
            caption += f"\n👨‍✈️ Капитан: {captain['name']} ({captain['phone']})"
            if len(boat_data['captain']) > 1:
                caption += "\n(Есть выбор капитанов)"
        
        await callback_query.message.answer_photo(
            FSInputFile(photo_path),
            caption=caption,
            reply_markup=get_boat_select_button(boat_name)
        )
        
    except Exception as e:
        logger.error(f"Ошибка загрузки фото {boat_name}: {e}")
        await callback_query.message.answer(
            f"🚤 {boat_name}\n📍 Причал: {boat_data['pier']}",
            reply_markup=get_boat_select_button(boat_name)
        )
    
    await callback_query.answer()

@dp.message(F.text == "Новая карточка")
async def new_card(message: types.Message):
    await start(message)

@dp.callback_query(F.data.startswith("boat_"))
async def process_boat(callback: types.CallbackQuery, state: FSMContext):
    boat_name = callback.data.removeprefix("boat_")
    boat_data = BOATS[boat_name]
    
    # Сохраняем основные данные
    await state.update_data(
        boat=boat_name,
        pier=boat_data['pier']
    )
    
    # Обработка капитанов
    captains = boat_data['captain']  # Всегда список
    
    if len(captains) > 1:  # Если несколько капитанов
        await state.set_state(Form.captain_choice)
        await ask_captain_choice(callback.message, captains)
    else:  # Если один капитан
        captain = captains[0]
        await state.update_data(
            captain_name=captain['name'],
            captain_phone=captain['phone']
        )
        await ask_hours(callback.message, state)  # Передаем state
    
    await callback.answer()

@dp.callback_query(F.data.startswith("capt_"), Form.captain_choice)
async def process_captain_choice(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    boat_data = BOATS[data['boat']]
    capt_idx = int(callback.data.removeprefix("capt_"))
    
    captain = boat_data['captain'][capt_idx]
    await state.update_data(
        captain_name=captain['name'],
        captain_phone=captain['phone']
    )
    
    await callback.message.edit_text(
        f"✅ Выбран капитан: {captain['name']}\n"
        f"📞 Телефон: {captain['phone']}"
    )
    await ask_hours(callback.message, state)  # Передаем state
    await callback.answer()

@dp.callback_query(F.data == "cancel_boat_selection")
async def cancel_boat_selection(callback: types.CallbackQuery, state: FSMContext):
    # Очищаем состояние
    await state.clear()
    
    # Создаем инлайн клавиатуру с кнопками лодок
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Сортируем названия лодок по алфавиту
    sorted_boat_names = sorted(BOATS.keys())
    
    # Создаем кнопки в 3 столбца
    buttons = []
    for i in range(0, len(sorted_boat_names), 3):
        row = []
        
        # Добавляем до 3 кнопок в строку
        for j in range(3):
            if i + j < len(sorted_boat_names):
                boat_name = sorted_boat_names[i + j]
                row.append(InlineKeyboardButton(
                    text=boat_name,
                    callback_data=f"boat_select:{boat_name}"
                ))
        
        buttons.append(row)
    
    keyboard.inline_keyboard = buttons
    
    # Редактируем сообщение с возвратом к выбору катера
    await callback.message.edit_text(
        "🚤 Выберите катер:",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.message(Form.hours)
async def process_hours(message: types.Message, state: FSMContext):
    allowed_hours = ['1', '1.5', '2', '2.5', '3', '4', '5', '6']
    
    if message.text not in allowed_hours:
        await message.answer(
            "❌ Выберите значение из предложенных:",
            reply_markup=get_hours_keyboard()
        )
        return
    
    # Удаляем клавиатуру выбора часов
    await message.answer(
        text=f"⏳ Выбрано часов аренды: {message.text}",
        reply_markup=types.ReplyKeyboardRemove()  # Убираем reply-клавиатуру
    )
    
    await state.update_data(hours=message.text)
    await state.set_state(Form.date)
    
    # Запускаем календарь
    await message.answer(
        "📅 Выберите дату аренды:",
        reply_markup=await SimpleCalendar().start_calendar()
    )

@dp.message(Form.date)
async def process_date(message: types.Message, state: FSMContext):
    await message.answer(
        "📅 Выберите дату:",
        reply_markup=await SimpleCalendar().start_calendar()
    )

# Добавляем новый обработчик календаря
@dp.callback_query(SimpleCalendarCallback.filter())
async def process_simple_calendar(
    callback_query: CallbackQuery, 
    callback_data: dict,
    state: FSMContext
):
    selected, date = await SimpleCalendar().process_selection(callback_query, callback_data)
    if selected:
        await state.update_data(date=date.strftime("%d.%m.%Y"))
        await callback_query.message.edit_text(
            f"✅ Выбрана дата: {date.strftime('%d.%m.%Y')}"
        )
        await callback_query.message.answer(
        "⏰ Выберите час начала аренды:",
        reply_markup=generate_hours_keyboard()
    )
    await state.set_state(Form.time_hour)

@dp.callback_query(F.data.startswith("hour_"), Form.time_hour)
async def process_hour_selection(callback: types.CallbackQuery, state: FSMContext):
    hour = callback.data.split("_")[1]
    await state.update_data(time_hour=hour)
    await callback.message.edit_text(
        f"Выбран час: {hour}:00\n"
        "Теперь выберите минуты:",
        reply_markup=generate_minutes_keyboard(int(hour))
    )
    await state.set_state(Form.time_minute)

@dp.callback_query(F.data.startswith("minute_"), Form.time_minute)
async def process_minute_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        time_str = callback.data.split("_")[1]
        await state.update_data(time=time_str)
        
        # Получаем данные из состояния
        data = await state.get_data()
        boat_name = data['boat']
        boat_data = BOATS[boat_name]
        
        # Показываем подтверждение с автоматическими данными
        await callback.message.edit_text(
            "👥 Введите количество гостей:"
        )
        
        # Переходим сразу к количеству гостей
        await state.set_state(Form.guests_count)
        
    except Exception as e:
        logger.error(f"Ошибка при выборе времени: {e}")
        await callback.answer("❌ Ошибка выбора времени", show_alert=True)


@dp.message(Form.guests_count)
async def process_guests_count(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число:")
        return
    
    await state.update_data(guests_count=message.text)
    
    # Получаем данные о лодке из состояния
    data = await state.get_data()
    boat_data = BOATS[data['boat']]
    
    # Показываем подтверждение данных капитана
    await message.answer(
        "🙋‍♂️ Введите имя гостя:"
    )
    
    # Переходим сразу к имени клиента
    await state.set_state(Form.client_name)

@dp.message(Form.client_name)
async def process_client_name(message: types.Message, state: FSMContext):
    if not re.match(r'^[A-Za-zА-Яа-я\s-]+$', message.text):
        await message.answer("❌ Имя может содержать только буквы, пробелы и дефисы. Введите снова:")
        return
    
    await state.update_data(client_name=message.text)
    await state.set_state(Form.remaining_payment)  # Переходим к вопросу об остатке
    await message.answer("💰 Введите остаток к оплате (в рублях):")

@dp.message(Form.remaining_payment)
async def process_remaining_payment(message: types.Message, state: FSMContext):
    if not re.match(r'^\d+$', message.text):
        await message.answer("❌ Введите сумму цифрами (например: 5000):")
        return
    
    data = await state.get_data()
    
    # Добавляем подтверждение данных
    confirmation_text = (
        "✅ Данные аренды:\n"
        f"🚤 Лодка: {data['boat']}\n"
        f"📍 Причал: {data['pier']}\n"
        f"👨‍✈️ Капитан: {data['captain_name']} ({data['captain_phone']})\n"
        f"📅 Дата: {data['date']} в {data['time']}\n"
        f"⏳ Продолжительность: {data['hours']} ч.\n"
        f"👥 Гости: {data['guests_count']}\n"
        f"👤 Клиент: {data['client_name']}\n"
        f"💰 Остаток к оплате: {message.text} руб."
    )
    
    await message.answer(confirmation_text)
    
    # Генерация PDF
    data['remaining_payment'] = message.text
    pdf_path = fill_pdf_template(data)
    
    with open(pdf_path, 'rb') as pdf_file:
        await message.answer_document(
            types.BufferedInputFile(pdf_file.read(), filename="аренда.pdf"),
            caption="📄 Ваша карточка аренды готова!"
        )
    
    os.remove(pdf_path)
    await state.clear()
    
    # Предлагаем создать новую карточку
    await message.answer(
        "Создать новую карточку:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Новая карточка")]],
            resize_keyboard=True
        )
    )

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())