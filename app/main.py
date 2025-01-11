from fastapi import FastAPI, HTTPException, Depends, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg
import os
import bcrypt
import jwt
from datetime import datetime, timedelta, date
from fastapi.security import OAuth2PasswordBearer
from supabase import create_client, Client
import uvicorn



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

# Модель для колонки Kanban
class KanbanColumn(BaseModel): 
    name: str

# Модель для задачи Kanban
class KanbanTask(BaseModel):
    column_id: int
    description: str

# Модель для активности здоровья
class HealthActivity(BaseModel):
    date: date
    steps: int
    calories: int
    activity: str

# Модель для глюкозы
class HealthGlucose(BaseModel):
    date: datetime
    glucose: float


# Модель для еды
class HealthFood(BaseModel):
  date: datetime
  calories: int
  water: float

# Подключение к базе данных
DATABASE_URL = f"postgres://{os.getenv('USER')}:{os.getenv('PASSWORD')}@{os.getenv('HOST')}:{os.getenv('PORT')}/{os.getenv('DBNAME')}?sslmode=require"

async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)

# Функции для работы с токенами
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, os.environ.get("SECRET_KEY"), algorithm="HS256")
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, os.environ.get("SECRET_KEY"), algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Endpoints для работы с пользователями
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

@app.get("/api/verify-token/")
async def verify_token_endpoint(token: str = Depends(oauth2_scheme)):
    try:
        payload = verify_token(token)
        return {"user_id": payload.get("user_id")}
    except HTTPException as e:
        raise e

# Endpoints для работы с задачами
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

@app.patch("/api/tasks/{task_id}/")
async def update_task(task_id: int, task: Task, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        existing_task = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1 AND user_id = $2", task_id, user_id)
        if not existing_task:
            raise HTTPException(status_code=404, detail="Task not found")

        await conn.execute(
            "UPDATE tasks SET completed = $1 WHERE id = $2 AND user_id = $3",
            task.completed, task_id, user_id
        )
        return {"message": "Task updated successfully"}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        await conn.close()

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

# Endpoints для работы с kanban доской (колонки)
@app.post("/api/kanban/")
async def create_kanban_column(column: KanbanColumn, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        column_id = await conn.fetchval(
            "INSERT INTO kanban_columns (user_id, name) VALUES ($1, $2) RETURNING id",
            user_id, column.name
        )
        return {"message": "Kanban column created successfully", "column_id": column_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.delete("/api/kanban/{column_id}/")
async def delete_kanban_column(column_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM kanban_columns WHERE id = $1 AND user_id = $2", column_id, user_id)
        return {"message": "Kanban column deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.post("/api/kanban/{column_id}/tasks/")
async def create_kanban_task(column_id: int, task: Task, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        task_id = await conn.fetchval(
            "INSERT INTO kanban_tasks (column_id, user_id, description) VALUES ($1, $2, $3) RETURNING id",
            column_id, user_id, task.description
        )
        return {"message": "Kanban task created successfully", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.patch("/api/kanban/{column_id}/")
async def update_kanban_column(column_id: int, column: KanbanColumn, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        await conn.execute(
            "UPDATE kanban_columns SET name = $1 WHERE id = $2 AND user_id = $3",
            column.name, column_id, user_id
        )
        return {"message": "Kanban column updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.get("/api/kanban/")
async def get_kanban_columns(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        columns = await conn.fetch(
            "SELECT id, name FROM kanban_columns WHERE user_id = $1",
            user_id
        )
        return {"columns": columns}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.get("/api/kanban/{column_id}/tasks/")
async def get_kanban_tasks(column_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        tasks = await conn.fetch(
            "SELECT id, description FROM kanban_tasks WHERE column_id = $1 AND user_id = $2",
            column_id, user_id
        )
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.patch("/api/kanban/{column_id}/tasks/{task_id}/")
async def update_kanban_task(column_id: int, task_id: int, task: Task, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        new_column_id = task.column_id if hasattr(task, 'column_id') else column_id
        
        await conn.execute(
            "UPDATE kanban_tasks SET column_id = $1, description = $2 WHERE id = $3 AND user_id = $4",
            new_column_id, task.description, task_id, user_id
        )
        return {"message": "Kanban task updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.delete("/api/kanban/{column_id}/tasks/{task_id}/")
async def delete_kanban_task(column_id: int, task_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM kanban_tasks WHERE id = $1 AND user_id = $2", task_id, user_id)
        return {"message": "Kanban task deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

# Endpoints для работы с здоровьем
@app.get("/api/health/activity/")
async def get_health_activity(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        activity = await conn.fetch("SELECT * FROM health_activity WHERE user_id = $1", user_id)
        return {"activity": activity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.post("/api/health/activity/")
async def create_health_activity(activity: HealthActivity, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        activity_id = await conn.fetchval(
            "INSERT INTO health_activity (user_id, date, steps, calories, activity) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            user_id, activity.date, activity.steps, activity.calories, activity.activity
        )
        return {"message": "Health activity created successfully", "activity_id": activity_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.delete("/api/health/activity/{activity_id}/")
async def delete_health_activity(activity_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM health_activity WHERE id = $1 AND user_id = $2", activity_id, user_id)
        return {"message": "Health activity deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


@app.get("/api/health/glucose/")
async def get_health_glucose(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        glucose = await conn.fetch("SELECT * FROM health_glucose WHERE user_id = $1", user_id)
        return {"glucose": glucose}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()
@app.post("/api/health/glucose/")
async def create_health_glucose(glucose: HealthGlucose, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        glucose_id = await conn.fetchval("INSERT INTO health_glucose (user_id, date, glucose) VALUES ($1, $2, $3) RETURNING id", user_id, glucose.date, glucose.glucose)
        return {"message": "Health glucose created successfully", "glucose_id": glucose_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()

@app.delete("/api/health/glucose/{glucose_id}/")
async def delete_health_glucose(glucose_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM health_glucose WHERE id = $1 AND user_id = $2", glucose_id, user_id)
        return {"message": "Health glucose deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()  




@app.post("/api/health/food/")
async def create_health_food(food: HealthFood, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        food_id = await conn.fetchval("INSERT INTO health_food (user_id, date, calories, water) VALUES ($1, $2, $3, $4) RETURNING id", user_id, food.date, food.calories, food.water)
        return {"message": "Health food created successfully", "food_id": food_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()
@app.delete("/api/health/food/{food_id}/")
async def delete_health_food(food_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM health_food WHERE id = $1 AND user_id = $2", food_id, user_id)
        return {"message": "Health food deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


@app.get("/api/health/food/")
async def get_health_food(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    user_id = payload.get("user_id")
    conn = await get_db_connection()
    try:
        food = await conn.fetch("SELECT * FROM health_food WHERE user_id = $1", user_id)
        return {"food": food}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()



# Endpoints для работы с Supabase

url: str = "https://ewtgjqcullvclwybsqco.supabase.co"
key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV3dGdqcWN1bGx2Y2x3eWJzcWNvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczNTc2NzIzNiwiZXhwIjoyMDUxMzQzMjM2fQ.NAbC1UQr-Ff_PEyLEhtR56EEQvah7jLbV0nChOTKL1o"
supabase: Client = create_client(url, key)

@app.post("/api/supabase/get-bucket/{user_id}")
async def post_bucket(user_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    auth_user_id = payload.get("user_id")
    try:
        response = supabase.storage.list_buckets()
        bucket = list(map(lambda x: x.id, response))
        if auth_user_id in bucket:
            return {"bucket": "bucket found"}
        else:
            response = supabase.storage.create_bucket(auth_user_id)
            return {"bucket": "bucket created",
                    "bucket_id": auth_user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/supabase/upload-file/{user_id}")
async def upload_file(user_id: int, file: UploadFile, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    auth_user_id = payload.get("user_id")
    try:
        response = supabase.storage.from_(auth_user_id).upload(file.filename, file.file)
        return {"file": "file uploaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/supabase/get-files/{user_id}")
async def get_files(user_id: int, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    auth_user_id = payload.get("user_id")
    try:
        response = supabase.storage.from_(auth_user_id).list()
        result = list(map(lambda x: x["name"] + " " + x["metadata"]["mimetype"], response))
        return {"file": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/supabase/delete-file/{user_id}")
async def delete_file(user_id: int, file_name: str, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    auth_user_id = payload.get("user_id")
    try:
        response = supabase.storage.from_(auth_user_id).remove([file_name])
        return {"file": "file deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/api/supabase/download-file/{user_id}")
async def download_file(user_id: int, file_name: str, token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    auth_user_id = payload.get("user_id")
    try:
        response = supabase.storage.from_(auth_user_id).create_signed_url(
            file_name, 60 * 60 * 60 * 24 * 30
        )
        return {"file_url": response["signedURL"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


