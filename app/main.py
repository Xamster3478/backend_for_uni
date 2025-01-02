from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg
import os
from dotenv import load_dotenv
import bcrypt  # Импортируем bcrypt для хеширования паролей

load_dotenv()  # Загружаем переменные окружения из файла .env

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешить все источники. Для безопасности лучше указать конкретные.
    allow_credentials=True,
    allow_methods=["*"],  # Разрешить все методы (GET, POST и т.д.)
    allow_headers=["*"],  # Разрешить все заголовки
)

# Модель для пользователя
class User(BaseModel):
    username: str
    password: str

# Подключение к базе данных
DATABASE_URL = f"postgres://{os.getenv('USER')}:{os.getenv('PASSWORD')}@{os.getenv('HOST')}:{os.getenv('PORT')}/{os.getenv('DBNAME')}?sslmode=require"

async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)

# Эндпоинт для создания пользователя
@app.post("/create-user/")
async def create_user(user: User):
    conn = await get_db_connection()
    try:
        # Хеширование пароля
        hashed_password = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
        
        user_id = await conn.fetchval(
            "INSERT INTO users (username, password) VALUES ($1, $2) RETURNING id",
            user.username, hashed_password.decode('utf-8')
        )
        return {"message": "User created successfully", "user_id": user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

# Эндпоинт для логина
@app.post("/login/")
async def login(user: User):
    conn = await get_db_connection()
    try:
        result = await conn.fetchrow(
            "SELECT id, password FROM users WHERE username = $1",
            user.username
        )
        if result and bcrypt.checkpw(user.password.encode('utf-8'), result['password'].encode('utf-8')):
            return {"message": "Login successful", "user_id": result['id']}
        else:
            raise HTTPException(status_code=400, detail="Invalid credentials")
    finally:
        await conn.close()