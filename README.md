# 🎬 Telegram Movie Bot

A collaborative Telegram bot that helps groups of friends pick a movie right inside a group chat.  
Filter by genre, year range, and rating — and get a movie suggestion with a link to HDRezka.

## 🚀 Features

- Inline buttons for easy selection
- Works in **group chats**
- Choose multiple genres
- Set year range and minimum rating
- Avoids repeating already shown movies
- Save movies to a personal **"Watch Later"** list
- Remove or mark movies as "Watched"

## 📦 Tech Stack

- Python 3.11+
- [Aiogram 3.x](https://docs.aiogram.dev/)
- Aiohttp (API requests)
- Aiosqlite (local storage)
- The Movie Database (TMDB) API

## 🛠 Setup
### Add your .env file

Create a .env file in the root directory and add:
- BOT_TOKEN=your_telegram_bot_token
- TMDB_API_KEY=your_tmdb_api_key

## ✅ Example Commands

- **/start** – Introduction
- **/random** – Start a new movie selection
- **/liked** – View saved "watch later" movies