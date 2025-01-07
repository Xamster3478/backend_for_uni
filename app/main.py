from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg
import os
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Модель для пользователя
class User(BaseModel):
    username: str
    password: str

# Модель для задачи
class Task(BaseModel):
    description: str
    completed: bool = False

# Подключение к базе данных
DATABASE_URL = f"postgres://{os.getenv('USER')}:{os.getenv('PASSWORD')}@{os.getenv('HOST')}:{os.getenv('PORT')}/{os.getenv('DBNAME')}?sslmode=require"

async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)

@app.post("/api/create-user/")
async def create_user(user: User):
    conn = await get_db_connection()
    try:
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

@app.post("/api/login/")
async def login(user: User):
    conn = await get_db_connection()
    try:
        result = await conn.fetchrow(
            "SELECT id, password FROM users WHERE username = $1",
            user.username
        )
        if result and bcrypt.checkpw(user.password.encode('utf-8'), result['password'].encode('utf-8')):
            token = create_access_token(data={"user_id": result['id']})
            return {"access_token": token, "token_type": "bearer"}
        else:
            raise HTTPException(status_code=400, detail="Invalid credentials")
    finally:
        await conn.close()

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, os.environ.get("SECRET_KEY"), algorithm="HS256")
    return encoded_jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.get("/api/verify-token/")
async def verify_token_endpoint(token: str = Depends(oauth2_scheme)):
    try:
        payload = verify_token(token)
        return {"user_id": payload.get("user_id")}
    except HTTPException as e:
        raise e

def verify_token(token: str):
    try:
        payload = jwt.decode(token, os.environ.get("SECRET_KEY"), algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Эндпоинт для создания задачи
@app.post("/api/tasks/")
async def create_task(task: Task, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        task_id = await conn.fetchval(
            "INSERT INTO tasks (user_id, description, completed) VALUES ($1, $2, $3) RETURNING id",
            user_id, task.description, task.completed
        )
        return {"message": "Task created successfully", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

# Эндпоинт для получения всех задач пользователя
@app.get("/api/tasks/")
async def get_tasks(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        tasks = await conn.fetch(
            "SELECT id, description, completed FROM tasks WHERE user_id = $1",
            user_id
        )
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

# Эндпоинт для удаления задачи
@app.delete("/api/tasks/{task_id}/")
async def delete_task(task_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        result = await conn.execute(
            "DELETE FROM tasks WHERE id = $1 AND user_id = $2",
            task_id, user_id
        )
        if result == "DELETE 1":
            return {"message": "Task deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()