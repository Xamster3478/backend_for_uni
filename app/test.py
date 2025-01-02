import asyncio
import asyncpg
import os
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

DATABASE_URL = f"postgres://{os.getenv('USER')}:{os.getenv('PASSWORD')}@{os.getenv('HOST')}:{os.getenv('PORT')}/{os.getenv('DBNAME')}?sslmode=require"

async def test_db_connection():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        print("Connection successful")
        await conn.close()
    except Exception as e:
        print(f"Connection failed: {e}")

# Запуск теста
asyncio.run(test_db_connection())