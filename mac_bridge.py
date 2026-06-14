import os
import subprocess
import traceback
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Автоматически берем ту папку, откуда запущен uvicorn
BASE_DIR = os.getcwd() 

class FileContent(BaseModel):
    text: str

@app.get("/read")
def read_file(path: str):
    full_path = os.path.join(BASE_DIR, path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(full_path, 'r', encoding='utf-8') as f:
        return {"content": f.read()}

@app.post("/write")
def write_file(path: str, content: FileContent):
    full_path = os.path.join(BASE_DIR, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content.text)
    return {"status": "success"}

@app.post("/bash")
def run_bash(cmd: str):
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=BASE_DIR, capture_output=True, text=True, timeout=120
        )
        return {
            "status": "success",
            "exit_code": result.returncode,
            "stdout": result.stdout[-5000:] if result.stdout else "",
            "stderr": result.stderr[-5000:] if result.stderr else ""
        }
    except Exception as e:
        # Ловим любые сбои на Mac и отправляем лог обратно агенту
        return {
            "status": "error",
            "stdout": "",
            "stderr": f"Внутренняя ошибка сервера Mac:\n{traceback.format_exc()}"
        }