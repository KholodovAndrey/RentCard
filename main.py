import os
import json
import re
import logging
import asyncio
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
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
    boat = State()
    hours = State()
    date = State()
    time = State()
    pier = State()
    guests_count = State()
    captain_name = State()
    captain_phone = State()
    client_name = State()
    remaining_payment = State()

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
    return user_id == ADMIN_ID

def get_boat_select_button(boat_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Выбрать {boat_name}", callback_data=f"boat_{boat_name}")
    return builder.as_markup()

def get_hours_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for i in range(1, 7):
        builder.add(KeyboardButton(text=str(i)))
    builder.adjust(3, 3)
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
    """Заполняет шаблон PDF (form.pdf) данными из data и возвращает путь к заполненному файлу"""
    from PyPDF2 import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from io import BytesIO
    
    # Загружаем шаблон
    template_path = os.path.join(CONFIGS_DIR, 'form.pdf')
    output_path = os.path.join(BASE_DIR, 'аренда.pdf')
    
    # Получаем путь к изображению катера
    boat_image_path = os.path.join(PHOTOS_DIR, BOATS[data['boat']])
    
    # Создаем временный PDF для заполнения данных
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    
    # Устанавливаем шрифт и цвет текста
    try:
        can.setFont('DejaVuSans', 10)
    except:
        can.setFont('Helvetica', 10)
    
    # Устанавливаем цвет текста (RGB)
    can.setFillColor(colors.Color(1, 1, 1))  # Темно-серый цвет
    
    # Добавляем изображение катера (координаты и размер можно настроить)
    add_image_to_pdf(can, boat_image_path, x=19, y=460, width=558, height=372, radius=30)
    
    # Заполняем данные в шаблоне (без названий полей)
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
    
    # Координаты (x, y) для каждого поля
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
    
    for field, value in fields.items():
        if field in coordinates:
            x, y = coordinates[field]
            can.drawString(x, y, value)
    
    can.save()
    
    # Перемещаем указатель в начало
    packet.seek(0)
    new_pdf = PdfReader(packet)
    
    # Читаем существующий PDF
    existing_pdf = PdfReader(open(template_path, "rb"))
    output = PdfWriter()
    
    # Добавляем заполненные данные на первую страницу
    page = existing_pdf.pages[0]
    page.merge_page(new_pdf.pages[0])
    output.add_page(page)
    
    # Сохраняем результат
    with open(output_path, "wb") as output_stream:
        output.write(output_stream)
    
    return output_path

@dp.message(Command("start"))
async def start(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    
    for boat_name, photo_name in BOATS.items():
        try:
            await message.answer_photo(
                FSInputFile(os.path.join(PHOTOS_DIR, photo_name)),
                caption=f"🚤 {boat_name}",
                reply_markup=get_boat_select_button(boat_name)
            )
        except Exception as e:
            logger.error(f"Ошибка загрузки фото {boat_name}: {e}")
            await message.answer(
                f"🚤 {boat_name}",
                reply_markup=get_boat_select_button(boat_name)
            )

@dp.message(F.text == "Новая карточка")
async def new_card(message: types.Message):
    await start(message)

@dp.callback_query(F.data.startswith("boat_"))
async def process_boat(callback: types.CallbackQuery, state: FSMContext):
    boat_name = callback.data.removeprefix("boat_")
    await state.update_data(boat=boat_name)
    await state.set_state(Form.hours)
    await callback.message.answer(
        f"Вы выбрали: {boat_name}\n\nСколько часов аренды?",
        reply_markup=get_hours_keyboard()
    )
    await callback.answer()

@dp.message(Form.hours)
async def process_hours(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) not in range(1, 7):
        await message.answer("❌ Введите число от 1 до 6:")
        return
    
    await state.update_data(hours=message.text)
    await state.set_state(Form.date)
    await message.answer("📅 Введите дату аренды (например: 15.07.2023):", reply_markup=types.ReplyKeyboardRemove())

@dp.message(Form.date)
async def process_date(message: types.Message, state: FSMContext):
    try:
        datetime.strptime(message.text, "%d.%m.%Y")
        await state.update_data(date=message.text)
        await state.set_state(Form.time)
        await message.answer("⏰ Введите время аренды (например: 14:00):")
    except ValueError:
        await message.answer("❌ Неверный формат даты. Введите дату в формате ДД.ММ.ГГГГ:")

@dp.message(Form.time)
async def process_time(message: types.Message, state: FSMContext):
    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(time=message.text)
        await state.set_state(Form.pier)
        await message.answer("📍 Введите причал посадки/высадки:")
    except ValueError:
        await message.answer("❌ Неверный формат времени. Введите время в формате ЧЧ:ММ:")

@dp.message(Form.pier)
async def process_pier(message: types.Message, state: FSMContext):
    await state.update_data(pier=message.text)
    await state.set_state(Form.guests_count)
    await message.answer("👥 Введите количество гостей:")

@dp.message(Form.guests_count)
async def process_guests_count(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число:")
        return
    
    await state.update_data(guests_count=message.text)
    await state.set_state(Form.captain_name)
    await message.answer("👨‍✈️ Введите имя капитана:")

@dp.message(Form.captain_name)
async def process_captain_name(message: types.Message, state: FSMContext):
    await state.update_data(captain_name=message.text)
    await state.set_state(Form.captain_phone)
    await message.answer("📞 Введите номер телефона капитана:")

@dp.message(Form.captain_phone)
async def process_captain_phone(message: types.Message, state: FSMContext):
    if not re.match(r'^(\+7|8)[\d\- ]{10,}$', message.text):
        await message.answer("❌ Введите корректный номер телефона (например: +79211234567 или 89211234567):")
        return
    
    await state.update_data(captain_phone=message.text)
    await state.set_state(Form.client_name)
    await message.answer("🙋‍♂️ Введите имя гостя:")

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
    # Проверяем, что введено число
    if not re.match(r'^\d+$', message.text):
        await message.answer("❌ Введите сумму цифрами (например: 5000):")
        return
    
    await state.update_data(remaining_payment=message.text)
    data = await state.get_data()
    
    # Устанавливаем фиксированное значение для предоплаты
    data['prepayment'] = "Предоплата внесена"
    
    # Заполняем шаблон PDF
    pdf_path = fill_pdf_template(data)
    
    # Отправляем заполненный PDF
    with open(pdf_path, 'rb') as pdf_file:
        await message.answer_document(
            types.BufferedInputFile(pdf_file.read(), filename="аренда.pdf"),
            caption="✅ Ваша карточка аренды готова!"
        )
    
    # Удаляем временный файл
    os.remove(pdf_path)
    await state.clear()
    
    # Показываем кнопку "Новая карточка" после отправки
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