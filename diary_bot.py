import asyncio
import logging
import json
import csv
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Float, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, \
    ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import openpyxl
import os

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = "8649780596:AAEnpGiotM12fzPpQ73LJg6xBHG37Uc8NQg"  # Вставьте сюда токен вашего бота
ADMIN_IDS = [454618194]  # ID администраторов через запятую, например: [123456789, 987654321]

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone=pytz.timezone('Europe/Moscow'))

# ==================== БАЗА ДАННЫХ ====================
engine = create_engine('sqlite:///diary.db', echo=False)
Base = declarative_base()
Session = sessionmaker(bind=engine)

# Таблица для связи многие-ко-многим (записи и теги)
entry_tags = Table('entry_tags', Base.metadata,
                   Column('entry_id', Integer, ForeignKey('entries.id', ondelete='CASCADE')),
                   Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'))
                   )


# Модели базы данных
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    pin_code = Column(String, nullable=True)
    is_premium = Column(Boolean, default=False)
    theme = Column(String, default='light')

    # Отношения
    entries = relationship('Entry', back_populates='user', cascade='all, delete-orphan')
    goals = relationship('Goal', back_populates='user', cascade='all, delete-orphan')
    habits = relationship('Habit', back_populates='user', cascade='all, delete-orphan')
    reminders = relationship('Reminder', back_populates='user', cascade='all, delete-orphan')
    categories = relationship('Category', back_populates='user', cascade='all, delete-orphan')
    tags = relationship('Tag', back_populates='user', cascade='all, delete-orphan')
    templates = relationship('Template', back_populates='user', cascade='all, delete-orphan')


class Category(Base):
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    color = Column(String, default='#808080')
    icon = Column(String, default='📁')

    # Отношения
    user = relationship('User', back_populates='categories')
    entries = relationship('Entry', back_populates='category', cascade='all, delete-orphan')


class Tag(Base):
    __tablename__ = 'tags'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)

    # Отношения
    user = relationship('User', back_populates='tags')
    entries = relationship('Entry', secondary=entry_tags, back_populates='tags', passive_deletes=True)


class Entry(Base):
    __tablename__ = 'entries'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    mood = Column(Integer, nullable=False)  # 1-10
    category_id = Column(Integer, ForeignKey('categories.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_encrypted = Column(Boolean, default=False)
    location = Column(String, nullable=True)
    weather = Column(String, nullable=True)

    # Отношения
    user = relationship('User', back_populates='entries')
    category = relationship('Category', back_populates='entries')
    tags = relationship('Tag', secondary=entry_tags, back_populates='entries', passive_deletes=True)
    attachments = relationship('Attachment', back_populates='entry', cascade='all, delete-orphan')


class Attachment(Base):
    __tablename__ = 'attachments'

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey('entries.id', ondelete='CASCADE'), nullable=False)
    file_type = Column(String, nullable=False)  # photo, document, audio
    file_id = Column(String, nullable=False)
    file_name = Column(String, nullable=True)

    # Отношения
    entry = relationship('Entry', back_populates='attachments')


class Goal(Base):
    __tablename__ = 'goals'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    target_date = Column(DateTime, nullable=True)
    progress = Column(Float, default=0)
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Отношения
    user = relationship('User', back_populates='goals')


class Habit(Base):
    __tablename__ = 'habits'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    frequency = Column(String, nullable=False)  # daily, weekly, monthly
    streak = Column(Integer, default=0)
    last_checked = Column(DateTime, nullable=True)

    # Отношения
    user = relationship('User', back_populates='habits')


class Reminder(Base):
    __tablename__ = 'reminders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    time = Column(String, nullable=False)  # Format: "HH:MM"
    message = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    # Отношения
    user = relationship('User', back_populates='reminders')


class Template(Base):
    __tablename__ = 'templates'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id', ondelete='SET NULL'), nullable=True)

    # Отношения
    user = relationship('User', back_populates='templates')
    category = relationship('Category')


# Создание таблиц
Base.metadata.create_all(engine)


# ==================== СОСТОЯНИЯ FSM ====================
class DiaryStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_content = State()
    waiting_for_mood = State()
    waiting_for_category = State()
    waiting_for_tags = State()
    waiting_for_pin = State()
    waiting_for_new_category = State()
    waiting_for_reminder_time = State()
    waiting_for_reminder_message = State()
    waiting_for_goal_title = State()
    waiting_for_goal_description = State()
    waiting_for_goal_date = State()
    waiting_for_habit_name = State()
    waiting_for_habit_frequency = State()
    waiting_for_search = State()
    waiting_for_template_name = State()
    waiting_for_template_content = State()
    waiting_for_edit_title = State()
    waiting_for_edit_content = State()


# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Новая запись"), KeyboardButton(text="📖 Мои записи")],
            [KeyboardButton(text="🏷️ Категории"), KeyboardButton(text="🔍 Поиск")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🎯 Цели и привычки")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_entry_actions_keyboard(entry_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Редактировать", callback_data=f"edit_{entry_id}"),
        InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_{entry_id}")
    )
    builder.row(
        InlineKeyboardButton(text="📎 Прикрепить файл", callback_data=f"attach_{entry_id}"),
        InlineKeyboardButton(text="📤 Экспорт", callback_data=f"export_{entry_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_entries")
    )
    return builder.as_markup()


def get_mood_keyboard():
    builder = InlineKeyboardBuilder()
    moods = ["1️⃣ 1-2", "2️⃣ 3-4", "3️⃣ 5-6", "4️⃣ 7-8", "5️⃣ 9-10"]
    for mood in moods:
        value = mood.split()[1]
        builder.add(InlineKeyboardButton(text=mood, callback_data=f"mood_{value}"))
    builder.adjust(5)
    return builder.as_markup()


def get_categories_keyboard(categories):
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.add(InlineKeyboardButton(
            text=f"{cat.icon} {cat.name}",
            callback_data=f"cat_{cat.id}"
        ))
    builder.add(InlineKeyboardButton(text="➕ Новая категория", callback_data="new_category"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    builder.adjust(2)
    return builder.as_markup()


def get_reminder_keyboard():
    builder = InlineKeyboardBuilder()
    times = ["09:00", "12:00", "15:00", "18:00", "21:00"]
    for time in times:
        builder.add(InlineKeyboardButton(text=time, callback_data=f"remind_{time}"))
    builder.add(InlineKeyboardButton(text="⏰ Своё время", callback_data="custom_time"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_settings"))
    builder.adjust(3)
    return builder.as_markup()


def get_settings_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔐 PIN-код", callback_data="set_pin"),
        InlineKeyboardButton(text="🎨 Тема", callback_data="set_theme")
    )
    builder.row(
        InlineKeyboardButton(text="⏰ Напоминания", callback_data="reminders"),
        InlineKeyboardButton(text="📤 Экспорт данных", callback_data="export_all")
    )
    builder.row(
        InlineKeyboardButton(text="📥 Импорт данных", callback_data="import_data"),
        InlineKeyboardButton(text="📝 Шаблоны", callback_data="templates")
    )
    builder.row(
        InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")
    )
    return builder.as_markup()


def get_export_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📄 TXT", callback_data="export_txt"),
        InlineKeyboardButton(text="📊 CSV", callback_data="export_csv"),
        InlineKeyboardButton(text="📑 JSON", callback_data="export_json")
    )
    builder.row(
        InlineKeyboardButton(text="📎 Excel", callback_data="export_excel"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_settings")
    )
    return builder.as_markup()


def get_goals_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎯 Новая цель", callback_data="new_goal"),
        InlineKeyboardButton(text="📋 Мои цели", callback_data="list_goals")
    )
    builder.row(
        InlineKeyboardButton(text="🔥 Новая привычка", callback_data="new_habit"),
        InlineKeyboardButton(text="📋 Мои привычки", callback_data="list_habits")
    )
    builder.row(
        InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main")
    )
    return builder.as_markup()


def get_templates_keyboard(templates):
    builder = InlineKeyboardBuilder()
    for tmpl in templates:
        builder.add(InlineKeyboardButton(
            text=f"📝 {tmpl.name}",
            callback_data=f"template_{tmpl.id}"
        ))
    builder.add(InlineKeyboardButton(text="➕ Новый шаблон", callback_data="new_template"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_settings"))
    builder.adjust(2)
    return builder.as_markup()


# ==================== УТИЛИТЫ ====================
class DiaryUtils:
    @staticmethod
    async def generate_mood_chart(entries):
        """Генерация графика настроения"""
        if not entries or len(entries) < 2:
            return None

        entries = sorted(entries, key=lambda x: x.created_at)[-30:]
        dates = [e.created_at.strftime('%d.%m') for e in entries]
        moods = [e.mood for e in entries]

        plt.figure(figsize=(10, 6))
        plt.plot(dates, moods, marker='o', linestyle='-', color='#4CAF50', linewidth=2, markersize=8)
        plt.fill_between(dates, moods, alpha=0.3, color='#4CAF50')
        plt.title('Динамика настроения за последние 30 дней', fontsize=16, pad=20)
        plt.xlabel('Дата', fontsize=12)
        plt.ylabel('Настроение (1-10)', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.yticks(range(1, 11))
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=100)
        buffer.seek(0)
        plt.close()

        return buffer

    @staticmethod
    async def generate_statistics(entries, goals, habits):
        """Генерация статистики"""
        if not entries:
            return "📊 **Статистика пуста**\n\nУ вас пока нет записей в дневнике."

        total_entries = len(entries)
        avg_mood = sum(e.mood for e in entries) / total_entries if total_entries else 0

        # Записи по периодам
        now = datetime.now()
        today = len([e for e in entries if e.created_at.date() == now.date()])
        week = len([e for e in entries if e.created_at.date() >= (now - timedelta(days=7)).date()])
        month = len([e for e in entries if e.created_at.date() >= (now - timedelta(days=30)).date()])

        # Категории
        categories = {}
        for e in entries:
            if e.category:
                categories[e.category.name] = categories.get(e.category.name, 0) + 1

        # Теги
        all_tags = []
        for e in entries:
            all_tags.extend([t.name for t in e.tags])
        top_tags = sorted(set(all_tags), key=lambda x: all_tags.count(x), reverse=True)[:5]

        stats = f"""📊 **СТАТИСТИКА ДНЕВНИКА**

📝 **Записи:**
• Всего: {total_entries}
• Сегодня: {today}
• За неделю: {week}
• За месяц: {month}

😊 **Настроение:**
• Среднее: {avg_mood:.1f}/10
• Лучшее: {max([e.mood for e in entries], default=0)}/10
• Худшее: {min([e.mood for e in entries], default=0)}/10

📁 **Категории:**
"""
        for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]:
            stats += f"• {cat}: {count} записей\n"

        stats += f"\n🏷️ **Популярные теги:**\n"
        if top_tags:
            for tag in top_tags:
                stats += f"• #{tag}: {all_tags.count(tag)} раз\n"
        else:
            stats += "• Пока нет тегов\n"

        stats += f"""\n🎯 **Цели:**
• Всего: {len(goals)}
• Выполнено: {len([g for g in goals if g.is_completed])}
• В процессе: {len([g for g in goals if not g.is_completed])}

🔥 **Привычки:**
• Всего: {len(habits)}
• Активных: {len([h for h in habits if h.streak > 0])}
• Лучшая серия: {max([h.streak for h in habits], default=0)} дней
"""
        return stats

    @staticmethod
    async def export_to_format(entries, format_type):
        """Экспорт записей в различных форматах"""
        buffer = BytesIO()
        filename = f"diary_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if format_type == 'json':
            data = []
            for e in entries:
                data.append({
                    'id': e.id,
                    'title': e.title,
                    'content': e.content,
                    'mood': e.mood,
                    'created_at': e.created_at.isoformat(),
                    'category': e.category.name if e.category else None,
                    'tags': [t.name for t in e.tags]
                })
            buffer.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
            buffer.seek(0)
            return buffer, f"{filename}.json"

        elif format_type == 'csv':
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['ID', 'Заголовок', 'Содержание', 'Настроение', 'Дата', 'Категория', 'Теги'])
            for e in entries:
                writer.writerow([
                    e.id,
                    e.title,
                    e.content.replace('\n', ' '),
                    e.mood,
                    e.created_at.strftime('%Y-%m-%d %H:%M'),
                    e.category.name if e.category else '',
                    ', '.join([t.name for t in e.tags])
                ])
            buffer.write(output.getvalue().encode('utf-8-sig'))
            buffer.seek(0)
            return buffer, f"{filename}.csv"

        elif format_type == 'excel':
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Дневник"

            headers = ['ID', 'Заголовок', 'Содержание', 'Настроение', 'Дата', 'Категория', 'Теги']
            ws.append(headers)

            for e in entries:
                ws.append([
                    e.id,
                    e.title,
                    e.content,
                    e.mood,
                    e.created_at.strftime('%Y-%m-%d %H:%M'),
                    e.category.name if e.category else '',
                    ', '.join([t.name for t in e.tags])
                ])

            wb.save(buffer)
            buffer.seek(0)
            return buffer, f"{filename}.xlsx"

        elif format_type == 'txt':
            text = "ДНЕВНИК\n" + "=" * 50 + "\n\n"
            for e in entries:
                text += f"""
ЗАПИСЬ #{e.id}
📅 {e.created_at.strftime('%d.%m.%Y %H:%M')}
📝 {e.title}
😊 Настроение: {e.mood}/10
📁 Категория: {e.category.name if e.category else 'Без категории'}
🏷️ Теги: {', '.join([t.name for t in e.tags]) if e.tags else 'Нет'}
{'-' * 40}
{e.content}
{'=' * 50}\n
"""
            buffer.write(text.encode('utf-8'))
            buffer.seek(0)
            return buffer, f"{filename}.txt"

        return None, None


# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    session = Session()

    # Проверяем, существует ли пользователь
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

    if not user:
        # Создаем нового пользователя
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
        session.add(user)
        session.commit()

        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            "Я твой личный дневник-помощник. Здесь ты можешь:\n"
            "📝 Записывать свои мысли и события\n"
            "😊 Отслеживать настроение\n"
            "🏷️ Сортировать записи по категориям\n"
            "📊 Смотреть статистику\n"
            "🎯 Ставить цели и привычки\n"
            "🔐 Защищать записи PIN-кодом\n\n"
            "Используй кнопки ниже для навигации!",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            f"С возвращением, {message.from_user.first_name}! 👋\n\n"
            "Чем займёмся сегодня?",
            reply_markup=get_main_keyboard()
        )

    session.close()


@dp.message(F.text == "📝 Новая запись")
async def new_entry(message: Message, state: FSMContext):
    """Начало создания новой записи"""
    await message.answer(
        "✏️ Введите заголовок новой записи:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Отмена")]],
            resize_keyboard=True
        )
    )
    await state.set_state(DiaryStates.waiting_for_title)


@dp.message(DiaryStates.waiting_for_title)
async def process_title(message: Message, state: FSMContext):
    """Обработка заголовка записи"""
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer(
            "Создание записи отменено.",
            reply_markup=get_main_keyboard()
        )
        return

    await state.update_data(title=message.text)
    await message.answer(
        "📝 Теперь напишите содержание записи:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Отмена")]],
            resize_keyboard=True
        )
    )
    await state.set_state(DiaryStates.waiting_for_content)


@dp.message(DiaryStates.waiting_for_content)
async def process_content(message: Message, state: FSMContext):
    """Обработка содержания записи"""
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer(
            "Создание записи отменено.",
            reply_markup=get_main_keyboard()
        )
        return

    await state.update_data(content=message.text)
    await message.answer(
        "😊 Оцените ваше настроение от 1 до 10:",
        reply_markup=get_mood_keyboard()
    )
    await state.set_state(DiaryStates.waiting_for_mood)


@dp.callback_query(DiaryStates.waiting_for_mood)
async def process_mood(callback: CallbackQuery, state: FSMContext):
    """Обработка настроения"""
    if callback.data.startswith('mood_'):
        mood = int(callback.data.split('_')[1])
        await state.update_data(mood=mood)

        session = Session()
        user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
        categories = session.query(Category).filter_by(user_id=user.id).all()

        if categories:
            await callback.message.edit_text(
                "📁 Выберите категорию для записи:",
                reply_markup=get_categories_keyboard(categories)
            )
            await state.set_state(DiaryStates.waiting_for_category)
        else:
            # Если нет категорий, создаем запись без категории
            data = await state.get_data()

            entry = Entry(
                user_id=user.id,
                title=data['title'],
                content=data['content'],
                mood=data['mood']
            )
            session.add(entry)
            session.commit()

            await callback.message.edit_text(
                "✅ Запись успешно создана!\n\n"
                f"📝 **{entry.title}**\n"
                f"😊 Настроение: {entry.mood}/10\n"
                f"📅 {entry.created_at.strftime('%d.%m.%Y %H:%M')}",
                parse_mode="Markdown"
            )
            await state.clear()

        session.close()

    await callback.answer()


@dp.callback_query(DiaryStates.waiting_for_category)
async def process_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории"""
    if callback.data == "new_category":
        await callback.message.edit_text(
            "✏️ Введите название новой категории:"
        )
        await state.set_state(DiaryStates.waiting_for_new_category)

    elif callback.data == "back_to_main":
        await state.clear()
        await callback.message.edit_text(
            "Создание записи отменено."
        )
        await callback.message.answer(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )

    elif callback.data.startswith('cat_'):
        category_id = int(callback.data.split('_')[1])
        data = await state.get_data()

        session = Session()
        user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()

        entry = Entry(
            user_id=user.id,
            title=data['title'],
            content=data['content'],
            mood=data['mood'],
            category_id=category_id
        )
        session.add(entry)
        session.commit()

        category = session.query(Category).filter_by(id=category_id).first()

        await callback.message.edit_text(
            f"✅ Запись успешно создана в категории {category.icon} {category.name}!\n\n"
            f"📝 **{entry.title}**\n"
            f"😊 Настроение: {entry.mood}/10\n"
            f"📅 {entry.created_at.strftime('%d.%m.%Y %H:%M')}",
            parse_mode="Markdown"
        )
        await state.clear()
        session.close()

    await callback.answer()


@dp.message(DiaryStates.waiting_for_new_category)
async def process_new_category(message: Message, state: FSMContext):
    """Создание новой категории"""
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer(
            "Создание категории отменено.",
            reply_markup=get_main_keyboard()
        )
        return

    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

    category = Category(
        user_id=user.id,
        name=message.text,
        icon="📁"
    )
    session.add(category)
    session.commit()

    await message.answer(
        f"✅ Категория '{message.text}' успешно создана!\n\n"
        "Теперь вы можете использовать её для записей.",
        reply_markup=get_main_keyboard()
    )

    # Возвращаемся к созданию записи
    data = await state.get_data()
    categories = session.query(Category).filter_by(user_id=user.id).all()

    if categories:
        await message.answer(
            "📁 Выберите категорию для записи:",
            reply_markup=get_categories_keyboard(categories)
        )
        await state.set_state(DiaryStates.waiting_for_category)
    else:
        # Если всё равно нет категорий (странно), создаем запись без категории
        entry = Entry(
            user_id=user.id,
            title=data['title'],
            content=data['content'],
            mood=data['mood']
        )
        session.add(entry)
        session.commit()

        await message.answer(
            "✅ Запись успешно создана!"
        )
        await state.clear()

    session.close()


@dp.message(F.text == "📖 Мои записи")
async def show_entries(message: Message):
    """Показать список записей"""
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

    entries = session.query(Entry).filter_by(user_id=user.id).order_by(Entry.created_at.desc()).limit(10).all()

    if not entries:
        await message.answer(
            "📖 У вас пока нет записей.\n\n"
            "Нажмите «📝 Новая запись», чтобы создать первую запись!",
            reply_markup=get_main_keyboard()
        )
        session.close()
        return

    text = "📖 **Последние записи:**\n\n"

    for i, entry in enumerate(entries, 1):
        mood_emoji = ["😢", "😕", "😐", "🙂", "😊"][(entry.mood - 1) // 2]
        text += f"{i}. {mood_emoji} **{entry.title}**\n"
        text += f"   📅 {entry.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        if entry.category:
            text += f"   {entry.category.icon} {entry.category.name}\n"
        text += f"   [Подробнее](command:entry_{entry.id})\n\n"

    # Создаем клавиатуру с кнопками для каждой записи
    builder = InlineKeyboardBuilder()
    for entry in entries[:5]:  # Максимум 5 кнопок
        builder.add(InlineKeyboardButton(
            text=f"{entry.title[:20]}...",
            callback_data=f"view_{entry.id}"
        ))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="📤 Экспорт всех", callback_data="export_all"))

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

    session.close()


@dp.callback_query(lambda c: c.data.startswith('view_'))
async def view_entry(callback: CallbackQuery):
    """Просмотр конкретной записи"""
    entry_id = int(callback.data.split('_')[1])

    session = Session()
    entry = session.query(Entry).filter_by(id=entry_id).first()

    if not entry:
        await callback.message.edit_text("Запись не найдена.")
        session.close()
        return

    mood_emoji = ["😢", "😕", "😐", "🙂", "😊"][(entry.mood - 1) // 2]

    text = f"""📝 **{entry.title}**

{entry.content}

{mood_emoji} **Настроение:** {entry.mood}/10
📅 **Дата:** {entry.created_at.strftime('%d.%m.%Y %H:%M')}
📁 **Категория:** {entry.category.icon + ' ' + entry.category.name if entry.category else 'Без категории'}
🏷️ **Теги:** {', '.join([t.name for t in entry.tags]) if entry.tags else 'Нет тегов'}

📎 **Вложения:** {len(entry.attachments)} файлов
"""

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=get_entry_actions_keyboard(entry.id)
    )

    session.close()
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('delete_'))
async def delete_entry(callback: CallbackQuery):
    """Удаление записи"""
    entry_id = int(callback.data.split('_')[1])

    session = Session()
    entry = session.query(Entry).filter_by(id=entry_id).first()

    if entry:
        session.delete(entry)
        session.commit()
        await callback.message.edit_text("✅ Запись успешно удалена!")
    else:
        await callback.message.edit_text("❌ Запись не найдена.")

    session.close()
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('edit_'))
async def edit_entry_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования записи"""
    entry_id = int(callback.data.split('_')[1])
    await state.update_data(edit_entry_id=entry_id)

    await callback.message.edit_text(
        "✏️ Введите новый заголовок записи:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data=f"view_{entry_id}")]]
        )
    )
    await state.set_state(DiaryStates.waiting_for_edit_title)
    await callback.answer()


@dp.message(DiaryStates.waiting_for_edit_title)
async def process_edit_title(message: Message, state: FSMContext):
    """Обработка нового заголовка"""
    data = await state.get_data()
    entry_id = data['edit_entry_id']

    session = Session()
    entry = session.query(Entry).filter_by(id=entry_id).first()

    if entry:
        entry.title = message.text
        session.commit()

        await message.answer(
            "✅ Заголовок обновлен!\n\n✏️ Введите новое содержание записи:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🔙 Отмена")]],
                resize_keyboard=True
            )
        )
        await state.set_state(DiaryStates.waiting_for_edit_content)
    else:
        await message.answer("❌ Запись не найдена.")
        await state.clear()

    session.close()


@dp.message(DiaryStates.waiting_for_edit_content)
async def process_edit_content(message: Message, state: FSMContext):
    """Обработка нового содержания"""
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer(
            "Редактирование отменено.",
            reply_markup=get_main_keyboard()
        )
        return

    data = await state.get_data()
    entry_id = data['edit_entry_id']

    session = Session()
    entry = session.query(Entry).filter_by(id=entry_id).first()

    if entry:
        entry.content = message.text
        entry.updated_at = datetime.utcnow()
        session.commit()

        await message.answer(
            "✅ Запись успешно обновлена!",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer("❌ Запись не найдена.")

    await state.clear()
    session.close()


@dp.message(F.text == "🏷️ Категории")
async def manage_categories(message: Message):
    """Управление категориями"""
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    categories = session.query(Category).filter_by(user_id=user.id).all()

    if not categories:
        text = "🏷️ У вас пока нет категорий.\n\nСоздайте первую категорию!"
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="➕ Создать категорию", callback_data="new_category"))
    else:
        text = "🏷️ **Ваши категории:**\n\n"
        for cat in categories:
            entries_count = session.query(Entry).filter_by(category_id=cat.id).count()
            text += f"{cat.icon} **{cat.name}** - {entries_count} записей\n"

        builder = InlineKeyboardBuilder()
        for cat in categories:
            builder.add(InlineKeyboardButton(
                text=f"{cat.icon} {cat.name}",
                callback_data=f"cat_{cat.id}"
            ))
        builder.add(InlineKeyboardButton(text="➕ Новая", callback_data="new_category"))
        builder.adjust(2)

    builder.row(InlineKeyboardButton(text="🔙 На главную", callback_data="back_to_main"))

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

    session.close()


@dp.message(F.text == "🔍 Поиск")
async def search_start(message: Message, state: FSMContext):
    """Начало поиска"""
    await message.answer(
        "🔍 Введите текст для поиска по заголовкам и содержанию записей:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Отмена")]],
            resize_keyboard=True
        )
    )
    await state.set_state(DiaryStates.waiting_for_search)


@dp.message(DiaryStates.waiting_for_search)
async def process_search(message: Message, state: FSMContext):
    """Обработка поиска"""
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer(
            "Поиск отменен.",
            reply_markup=get_main_keyboard()
        )
        return

    search_text = message.text.lower()

    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

    entries = session.query(Entry).filter_by(user_id=user.id).all()
    results = []

    for entry in entries:
        if (search_text in entry.title.lower() or
                search_text in entry.content.lower() or
                any(search_text in tag.name.lower() for tag in entry.tags)):
            results.append(entry)

    if not results:
        await message.answer(
            f"🔍 По запросу '{message.text}' ничего не найдено.",
            reply_markup=get_main_keyboard()
        )
    else:
        text = f"🔍 **Найдено записей: {len(results)}**\n\n"

        builder = InlineKeyboardBuilder()
        for entry in results[:10]:
            text += f"• {entry.title} ({entry.created_at.strftime('%d.%m.%Y')})\n"
            builder.add(InlineKeyboardButton(
                text=entry.title[:20],
                callback_data=f"view_{entry.id}"
            ))

        builder.adjust(1)
        await message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )

    await state.clear()
    session.close()


@dp.message(F.text == "📊 Статистика")
async def show_statistics(message: Message):
    """Показать статистику"""
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

    entries = session.query(Entry).filter_by(user_id=user.id).all()
    goals = session.query(Goal).filter_by(user_id=user.id).all()
    habits = session.query(Habit).filter_by(user_id=user.id).all()

    stats_text = await DiaryUtils.generate_statistics(entries, goals, habits)

    # Генерируем график настроения
    chart_buffer = await DiaryUtils.generate_mood_chart(entries)

    if chart_buffer:
        # Сохраняем буфер в временный файл для отправки
        with open('temp_chart.png', 'wb') as f:
            f.write(chart_buffer.getvalue())

        await message.answer_photo(
            FSInputFile('temp_chart.png'),
            caption=stats_text,
            parse_mode="Markdown"
        )

        # Удаляем временный файл
        os.remove('temp_chart.png')
    else:
        await message.answer(
            stats_text,
            parse_mode="Markdown"
        )

    session.close()


@dp.message(F.text == "🎯 Цели и привычки")
async def goals_and_habits_menu(message: Message):
    """Меню целей и привычек"""
    await message.answer(
        "🎯 **Цели и привычки**\n\n"
        "Здесь вы можете ставить цели и отслеживать привычки.",
        parse_mode="Markdown",
        reply_markup=get_goals_keyboard()
    )


@dp.callback_query(lambda c: c.data == "new_goal")
async def new_goal_start(callback: CallbackQuery, state: FSMContext):
    """Создание новой цели"""
    await callback.message.edit_text(
        "🎯 Введите название цели:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_goals")]]
        )
    )
    await state.set_state(DiaryStates.waiting_for_goal_title)
    await callback.answer()


@dp.message(DiaryStates.waiting_for_goal_title)
async def process_goal_title(message: Message, state: FSMContext):
    """Обработка названия цели"""
    await state.update_data(goal_title=message.text)

    await message.answer(
        "📝 Введите описание цели (или отправьте '-' чтобы пропустить):",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Отмена")]],
            resize_keyboard=True
        )
    )
    await state.set_state(DiaryStates.waiting_for_goal_description)


@dp.message(DiaryStates.waiting_for_goal_description)
async def process_goal_description(message: Message, state: FSMContext):
    """Обработка описания цели"""
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer(
            "Создание цели отменено.",
            reply_markup=get_main_keyboard()
        )
        return

    description = None if message.text == '-' else message.text
    await state.update_data(goal_description=description)

    await message.answer(
        "📅 Введите дату достижения цели (в формате ДД.ММ.ГГГГ)\n"
        "Или отправьте '-' чтобы без срока:"
    )
    await state.set_state(DiaryStates.waiting_for_goal_date)


@dp.message(DiaryStates.waiting_for_goal_date)
async def process_goal_date(message: Message, state: FSMContext):
    """Обработка даты цели"""
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer(
            "Создание цели отменено.",
            reply_markup=get_main_keyboard()
        )
        return

    data = await state.get_data()

    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

    target_date = None
    if message.text != '-':
        try:
            target_date = datetime.strptime(message.text, '%d.%m.%Y')
        except ValueError:
            await message.answer("❌ Неверный формат даты. Попробуйте еще раз:")
            return

    goal = Goal(
        user_id=user.id,
        title=data['goal_title'],
        description=data['goal_description'],
        target_date=target_date
    )
    session.add(goal)
    session.commit()

    await message.answer(
        f"✅ Цель '{data['goal_title']}' успешно создана!",
        reply_markup=get_main_keyboard()
    )

    await state.clear()
    session.close()


@dp.callback_query(lambda c: c.data == "new_habit")
async def new_habit_start(callback: CallbackQuery, state: FSMContext):
    """Создание новой привычки"""
    await callback.message.edit_text(
        "🔥 Введите название привычки:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_goals")]]
        )
    )
    await state.set_state(DiaryStates.waiting_for_habit_name)
    await callback.answer()


@dp.message(DiaryStates.waiting_for_habit_name)
async def process_habit_name(message: Message, state: FSMContext):
    """Обработка названия привычки"""
    await state.update_data(habit_name=message.text)

    # Создаем клавиатуру для выбора частоты
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Ежедневно", callback_data="freq_daily"),
        InlineKeyboardButton(text="Еженедельно", callback_data="freq_weekly")
    )
    builder.row(
        InlineKeyboardButton(text="Ежемесячно", callback_data="freq_monthly"),
        InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_goals")
    )

    await message.answer(
        "📅 Выберите частоту выполнения:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(DiaryStates.waiting_for_habit_frequency)


@dp.callback_query(DiaryStates.waiting_for_habit_frequency)
async def process_habit_frequency(callback: CallbackQuery, state: FSMContext):
    """Обработка частоты привычки"""
    if callback.data == "back_to_goals":
        await state.clear()
        await callback.message.edit_text("Создание привычки отменено.")
        await callback.answer()
        return

    frequency = callback.data.split('_')[1]
    data = await state.get_data()

    session = Session()
    user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()

    habit = Habit(
        user_id=user.id,
        name=data['habit_name'],
        frequency=frequency
    )
    session.add(habit)
    session.commit()

    await callback.message.edit_text(
        f"✅ Привычка '{data['habit_name']}' успешно создана!\n"
        f"Частота: {frequency}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 К целям", callback_data="back_to_goals")]]
        )
    )

    await state.clear()
    session.close()
    await callback.answer()


@dp.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message):
    """Меню настроек"""
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

    pin_status = "🔒 Установлен" if user.pin_code else "🔓 Не установлен"

    text = f"""⚙️ **НАСТРОЙКИ**

👤 **Профиль:**
• ID: {user.telegram_id}
• Имя: {user.first_name}
• Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}

🔐 **Безопасность:**
• PIN-код: {pin_status}

📊 **Статистика:**
• Всего записей: {session.query(Entry).filter_by(user_id=user.id).count()}
• Категорий: {session.query(Category).filter_by(user_id=user.id).count()}
• Целей: {session.query(Goal).filter_by(user_id=user.id).count()}
• Привычек: {session.query(Habit).filter_by(user_id=user.id).count()}
"""

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=get_settings_keyboard()
    )

    session.close()


@dp.callback_query(lambda c: c.data == "set_pin")
async def set_pin_start(callback: CallbackQuery, state: FSMContext):
    """Установка PIN-кода"""
    await callback.message.edit_text(
        "🔐 Введите 4-значный PIN-код для защиты дневника:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_settings")]]
        )
    )
    await state.set_state(DiaryStates.waiting_for_pin)
    await callback.answer()


@dp.message(DiaryStates.waiting_for_pin)
async def process_pin(message: Message, state: FSMContext):
    """Обработка PIN-кода"""
    if len(message.text) == 4 and message.text.isdigit():
        session = Session()
        user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

        user.pin_code = message.text
        session.commit()

        await message.answer(
            "✅ PIN-код успешно установлен!",
            reply_markup=get_main_keyboard()
        )
        session.close()
        await state.clear()
    else:
        await message.answer(
            "❌ PIN-код должен состоять из 4 цифр. Попробуйте еще раз:"
        )


@dp.callback_query(lambda c: c.data == "reminders")
async def reminders_menu(callback: CallbackQuery):
    """Меню напоминаний"""
    session = Session()
    user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
    reminders = session.query(Reminder).filter_by(user_id=user.id).all()

    if not reminders:
        text = "⏰ У вас пока нет напоминаний.\n\nУстановите напоминание, чтобы не забывать писать в дневник!"
    else:
        text = "⏰ **Ваши напоминания:**\n\n"
        for r in reminders:
            status = "✅" if r.is_active else "❌"
            text += f"{status} {r.time} - {r.message}\n"

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Добавить", callback_data="add_reminder"))
    if reminders:
        builder.add(InlineKeyboardButton(text="❌ Удалить все", callback_data="delete_all_reminders"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_settings"))
    builder.adjust(2)

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

    session.close()
    await callback.answer()


@dp.callback_query(lambda c: c.data == "add_reminder")
async def add_reminder_start(callback: CallbackQuery, state: FSMContext):
    """Добавление напоминания"""
    await callback.message.edit_text(
        "⏰ Выберите время для напоминания:",
        reply_markup=get_reminder_keyboard()
    )
    await state.set_state(DiaryStates.waiting_for_reminder_time)
    await callback.answer()


@dp.callback_query(DiaryStates.waiting_for_reminder_time)
async def process_reminder_time(callback: CallbackQuery, state: FSMContext):
    """Обработка времени напоминания"""
    if callback.data == "back_to_settings":
        await state.clear()
        await reminders_menu(callback)
        return

    if callback.data == "custom_time":
        await callback.message.edit_text(
            "⏰ Введите время в формате ЧЧ:ММ (например, 14:30):",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="reminders")]]
            )
        )
        return

    if callback.data.startswith('remind_'):
        time = callback.data.split('_')[1]
        await state.update_data(reminder_time=time)

        await callback.message.edit_text(
            f"⏰ Время: {time}\n\n"
            "📝 Введите текст напоминания:"
        )
        await state.set_state(DiaryStates.waiting_for_reminder_message)

    await callback.answer()


@dp.message(DiaryStates.waiting_for_reminder_time)
async def process_custom_time(message: Message, state: FSMContext):
    """Обработка пользовательского времени"""
    try:
        # Проверяем формат времени
        time_obj = datetime.strptime(message.text, '%H:%M')
        time_str = message.text

        await state.update_data(reminder_time=time_str)

        await message.answer(
            f"⏰ Время: {time_str}\n\n"
            "📝 Введите текст напоминания:"
        )
        await state.set_state(DiaryStates.waiting_for_reminder_message)
    except ValueError:
        await message.answer(
            "❌ Неверный формат времени. Используйте ЧЧ:ММ (например, 14:30):"
        )


@dp.message(DiaryStates.waiting_for_reminder_message)
async def process_reminder_message(message: Message, state: FSMContext):
    """Обработка текста напоминания"""
    data = await state.get_data()
    time_str = data['reminder_time']

    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

    reminder = Reminder(
        user_id=user.id,
        time=time_str,
        message=message.text
    )
    session.add(reminder)
    session.commit()

    # Добавляем в планировщик
    hour, minute = map(int, time_str.split(':'))
    scheduler.add_job(
        send_reminder,
        CronTrigger(hour=hour, minute=minute, timezone=pytz.timezone('Europe/Moscow')),
        args=[user.telegram_id, message.text],
        id=f"reminder_{user.id}_{reminder.id}"
    )

    await message.answer(
        f"✅ Напоминание установлено на {time_str}!\n"
        f"Текст: {message.text}",
        reply_markup=get_main_keyboard()
    )

    await state.clear()
    session.close()


async def send_reminder(telegram_id: int, text: str):
    """Отправка напоминания"""
    try:
        await bot.send_message(
            telegram_id,
            f"⏰ **НАПОМИНАНИЕ**\n\n{text}\n\n"
            "Не забудьте сделать запись в дневнике! 📝",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Failed to send reminder: {e}")


@dp.callback_query(lambda c: c.data == "export_all")
async def export_all_start(callback: CallbackQuery):
    """Начало экспорта всех записей"""
    await callback.message.edit_text(
        "📤 Выберите формат экспорта:",
        reply_markup=get_export_keyboard()
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('export_'))
async def process_export(callback: CallbackQuery):
    """Экспорт записей"""
    format_type = callback.data.split('_')[1]

    if format_type == "back":
        await settings_menu(callback.message)
        await callback.answer()
        return

    session = Session()
    user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
    entries = session.query(Entry).filter_by(user_id=user.id).order_by(Entry.created_at).all()

    if not entries:
        await callback.message.edit_text("❌ Нет записей для экспорта.")
        session.close()
        await callback.answer()
        return

    await callback.message.edit_text("⏳ Генерация файла экспорта...")

    buffer, filename = await DiaryUtils.export_to_format(entries, format_type)

    if buffer:
        # Сохраняем буфер во временный файл
        with open(f'temp_{filename}', 'wb') as f:
            f.write(buffer.getvalue())

        await callback.message.answer_document(
            FSInputFile(f'temp_{filename}'),
            caption=f"✅ Экспорт завершен!\nФормат: {format_type.upper()}"
        )

        # Удаляем временный файл
        os.remove(f'temp_{filename}')
    else:
        await callback.message.edit_text("❌ Ошибка при экспорте.")

    session.close()
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Возврат в главное меню"""
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_settings")
async def back_to_settings(callback: CallbackQuery):
    """Возврат в меню настроек"""
    await settings_menu(callback.message)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_goals")
async def back_to_goals(callback: CallbackQuery):
    """Возврат в меню целей"""
    await goals_and_habits_menu(callback.message)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_entries")
async def back_to_entries(callback: CallbackQuery):
    """Возврат к списку записей"""
    await show_entries(callback.message)
    await callback.answer()


@dp.message(F.text == "❓ Помощь")
async def help_command(message: Message):
    """Справка по боту"""
    help_text = """❓ **ПОМОЩЬ ПО БОТУ**

📝 **Основные функции:**

• **📝 Новая запись** - создать запись в дневнике
• **📖 Мои записи** - просмотреть все записи
• **🏷️ Категории** - управление категориями
• **🔍 Поиск** - поиск по записям
• **📊 Статистика** - статистика и графики
• **🎯 Цели и привычки** - постановка целей
• **⚙️ Настройки** - настройки бота

🔐 **Безопасность:**
Вы можете установить PIN-код для защиты записей

⏰ **Напоминания:**
Бот может напоминать о необходимости сделать запись

📤 **Экспорт:**
Все записи можно экспортировать в TXT, CSV, JSON или Excel

📎 **Вложения:**
К записям можно прикреплять фото и документы

🎨 **Команды:**
/start - запуск бота
/help - эта справка
/cancel - отмена текущего действия
"""
    await message.answer(help_text, parse_mode="Markdown")


@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    """Отмена текущего действия"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного действия.")
        return

    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=get_main_keyboard()
    )


@dp.message(F.text == "🔙 Отмена")
async def cancel_button(message: Message, state: FSMContext):
    """Обработка кнопки отмены"""
    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=get_main_keyboard()
    )


# ==================== ЗАПУСК БОТА ====================
async def on_startup():
    """Действия при запуске бота"""
    # Создаем таблицы в базе данных
    Base.metadata.create_all(engine)

    # Небольшая задержка для инициализации БД
    await asyncio.sleep(0.5)

    # Загружаем напоминания из базы данных
    session = Session()
    try:
        reminders = session.query(Reminder).filter_by(is_active=True).all()

        for reminder in reminders:
            try:
                hour, minute = map(int, reminder.time.split(':'))
                scheduler.add_job(
                    send_reminder,
                    CronTrigger(hour=hour, minute=minute, timezone=pytz.timezone('Europe/Moscow')),
                    args=[reminder.user.telegram_id, reminder.message],
                    id=f"reminder_{reminder.user_id}_{reminder.id}",
                    replace_existing=True
                )
            except Exception as e:
                logging.error(f"Failed to schedule reminder {reminder.id}: {e}")

        logging.info(f"Loaded {len(reminders)} reminders")
    except Exception as e:
        logging.error(f"Error loading reminders: {e}")
    finally:
        session.close()

    # Запускаем планировщик
    scheduler.start()

    logging.info("Бот успешно запущен!")


async def on_shutdown():
    """Действия при остановке бота"""
    scheduler.shutdown()
    logging.info("Бот остановлен.")


async def main():
    """Главная функция"""
    await on_startup()

    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
