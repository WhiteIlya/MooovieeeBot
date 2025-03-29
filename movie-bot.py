import asyncio
import random
import aiohttp
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
from aiogram.filters import Command
from config import BOT_TOKEN, TMDB_API_KEY

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_NAME = "moviebot.db"
GENRES = {
    'action': 28, 'adventure': 12, 'animation': 16, 'comedy': 35, 'crime': 80, 'documentary': 99,
    'drama': 18, 'family': 10751, 'fantasy': 14, 'history': 36, 'horror': 27, 'music': 10402,
    'mystery': 9648, 'romance': 10749, 'sci-fi': 878, 'tv movie': 10770, 'thriller': 53,
    'war': 10752, 'western': 37
}

chat_states = {}

async def init_db(): 
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS liked_movies (
                chat_id INTEGER,
                tmdb_id INTEGER,
                title TEXT,
                poster_url TEXT,
                overview TEXT,
                added_by TEXT,
                added_at TEXT,
                PRIMARY KEY (chat_id, tmdb_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shown_movies (
                chat_id INTEGER,
                tmdb_id INTEGER,
                PRIMARY KEY (chat_id, tmdb_id)
            )
        """)
        await db.commit()

@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("Привет! Напиши /random чтобы я помог выбрать фильм 🎬")

@dp.message(Command("random"))
async def random_handler(message: Message):
    chat_id = message.chat.id
    chat_states[chat_id] = {
        "genres": [],
        "step": "year",
        "shown_movie_ids": set(),
        "last_messages": []
    }
    await message.answer("Выбери жанры:", reply_markup=create_genre_keyboard())

@dp.message(Command("liked"))
async def show_liked(message: Message):
    chat_id = message.chat.id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tmdb_id, title, poster_url FROM liked_movies WHERE chat_id = ?", (chat_id,)) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return await message.answer("Список 'посмотреть позже' пуст 💤")

        for tmdb_id, title, poster_url in rows:
            caption = f"<b>{title}</b>"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="👀 Просмотрено", callback_data=f"remove_liked:{tmdb_id}"),
                InlineKeyboardButton(text="❌ Удалить", callback_data=f"remove_liked:{tmdb_id}")
            ]])
            if poster_url:
                await message.answer_photo(photo=poster_url, caption=caption, parse_mode="HTML", reply_markup=keyboard)
            else:
                await message.answer(caption, parse_mode="HTML", reply_markup=keyboard)

@dp.message()
async def handle_chat_input(message: Message):
    chat_id = message.chat.id
    if chat_id not in chat_states or "step" not in chat_states[chat_id]:
        return

    state = chat_states[chat_id]

    if state["step"] == "year":
        year_range = message.text.strip()
        start_year = end_year = None
        if "-" in year_range:
            parts = year_range.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                start_year, end_year = int(parts[0]), int(parts[1])
        elif year_range.isdigit():
            start_year = end_year = int(year_range)

        state["years"] = (start_year, end_year)
        state["step"] = "rating"
        await message.answer("А теперь введи минимальный рейтинг от 0 до 10 (например: 7.5):")

    elif state["step"] == "rating":
        try:
            rating = float(message.text.strip())
            if rating < 0 or rating > 10:
                raise ValueError
        except ValueError:
            return await message.answer("Рейтинг должен быть числом от 0 до 10. Попробуй снова.")

        state["rating"] = rating
        state["step"] = None
        await send_random_movie(chat_id, message)

@dp.callback_query(lambda c: c.data.startswith("toggle_genre") or c.data == "genre_done")
async def genre_callback(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    state = chat_states.get(chat_id, {"genres": []})
    genre_ids = state["genres"]

    if callback.data.startswith("toggle_genre"):
        genre_id = callback.data.split(":")[1]
        if genre_id in genre_ids:
            genre_ids.remove(genre_id)
        else:
            genre_ids.append(genre_id)
        state["genres"] = genre_ids
        chat_states[chat_id] = state
        await callback.message.edit_reply_markup(reply_markup=create_genre_keyboard(selected=genre_ids))
        await callback.answer()

    elif callback.data == "genre_done":
        if not genre_ids:
            await callback.answer("Выбери хотя бы один жанр!", show_alert=True)
            return
        state["step"] = "year"
        chat_states[chat_id] = state
        await callback.message.answer("Теперь введи диапазон лет (например: 2010-2020) или оставь пустым:")
        await callback.answer()

@dp.callback_query(lambda c: c.data == "try_again")
async def handle_try_again(callback: CallbackQuery):
    await send_random_movie(callback.message.chat.id, callback.message)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "reset")
async def handle_reset(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    shown_ids = chat_states.get(chat_id, {}).get("shown_movie_ids", set())
    chat_states[chat_id] = {
        "genres": [],
        "step": "year",
        "shown_movie_ids": shown_ids
    }
    await callback.message.answer("Сброс настроек. Выбери жанры:", reply_markup=create_genre_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("like_movie:"))
async def handle_like(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    tmdb_id = int(callback.data.split(":")[1])
    user = callback.from_user.full_name

    title = (callback.message.caption or "").split("\n")[0]
    poster_file_id = callback.message.photo[-1].file_id if callback.message.photo else ""
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR IGNORE INTO liked_movies (chat_id, tmdb_id, title, poster_url, overview, added_by, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            chat_id, tmdb_id,
            title,
            poster_file_id,
            "",
            user,
            datetime.utcnow().isoformat()
        ))
        await db.commit()

    await callback.answer("Добавлено в 'посмотреть позже' ✅")


async def send_random_movie(chat_id, target):
    state = chat_states.get(chat_id)
    if not state:
        return await target.answer("Начни с команды /random")

    genre_ids = state.get("genres", [])
    start_year, end_year = state.get("years", (None, None))
    rating = state.get("rating", 0)

    async with aiosqlite.connect(DB_NAME) as db:
        async with aiohttp.ClientSession() as session:
            url = "https://api.themoviedb.org/3/discover/movie"
            params = {
                "api_key": TMDB_API_KEY,
                "with_genres": ','.join(genre_ids),
                "sort_by": "popularity.desc",
                "language": "ru-RU",
                "include_adult": "false",
                "vote_average.gte": rating
            }
            if start_year:
                params["primary_release_date.gte"] = f"{start_year}-01-01"
            if end_year:
                params["primary_release_date.lte"] = f"{end_year}-12-31"

            async with session.get(url, params=params) as resp:
                data = await resp.json()
                shown = set()
                async with db.execute("SELECT tmdb_id FROM shown_movies WHERE chat_id = ?", (chat_id,)) as cursor:
                    async for row in cursor:
                        shown.add(row[0])
                results = [r for r in data.get("results", []) if r["id"] not in shown]

                if not results:
                    await target.answer("Все фильмы уже были показаны. Сбросьте настройки или измените параметры.")
                    return

                movie = random.choice(results)
                await db.execute("INSERT OR IGNORE INTO shown_movies (chat_id, tmdb_id) VALUES (?, ?)", (chat_id, movie["id"]))
                await db.commit()

                title = movie['title']
                overview = movie.get("overview") or "Описание отсутствует."
                poster_path = movie.get('poster_path')
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                search_url = f"https://hdrezka.ag/search/?do=search&subaction=search&q={title.replace(' ', '+')}"

                caption = (
                    f"*{title}*\n\n"
                    f"{overview or 'Описание отсутствует.'}\n\n"
                    f"[Смотреть на HDRezka]({search_url})"
                )


                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🔁 Ещё раз", callback_data="try_again"),
                        InlineKeyboardButton(text="📌 Сохранить", callback_data=f"like_movie:{movie['id']}"),
                        InlineKeyboardButton(text="🗑 Сбросить", callback_data="reset")
                    ]
                ])

                last_msgs = chat_states[chat_id].get("last_messages", [])
                if len(last_msgs) >= 2:
                    msg_id_to_delete = last_msgs.pop(0)
                    try:
                        await bot.delete_message(chat_id, msg_id_to_delete)
                    except:
                        pass

                if poster_url:
                    msg = await target.answer_photo(photo=poster_url, caption=caption, parse_mode="Markdown", reply_markup=keyboard)
                else:
                    msg = await target.answer(caption, parse_mode="Markdown", reply_markup=keyboard)

                last_msgs.append(msg.message_id)
                chat_states[chat_id]["last_messages"] = last_msgs

@dp.callback_query(lambda c: c.data.startswith("remove_liked:"))
async def remove_liked(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    tmdb_id = int(callback.data.split(":")[1])

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM liked_movies WHERE chat_id = ? AND tmdb_id = ?", (chat_id, tmdb_id))
        await db.commit()

    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer("Удалено из списка ✅")

def create_genre_keyboard(selected=None):
    selected = [str(g) for g in selected or []]
    keyboard = []
    for genre, genre_id in GENRES.items():
        emoji = "✅" if str(genre_id) in selected else "➕"
        button = InlineKeyboardButton(text=f"{emoji} {genre.title()}", callback_data=f"toggle_genre:{genre_id}")
        keyboard.append(button)
    rows = [keyboard[i:i + 3] for i in range(0, len(keyboard), 3)]
    rows.append([InlineKeyboardButton(text="🎬 Готово", callback_data="genre_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
