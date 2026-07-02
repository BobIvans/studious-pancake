import os
import traceback
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

BASE_DIR = os.getcwd()

SENSITIVE_FILES = {"wallet.json", ".env", ".secrets.baseline", "helius-sanctum-lst-webhook.json"}

class FileContent(BaseModel):
    text: str

@app.get("/read")
def read_file(path: str):
    resolved_path = os.path.abspath(os.path.join(BASE_DIR, path))
    if not resolved_path.startswith(os.path.abspath(BASE_DIR)):
        raise HTTPException(status_code=403, detail="Directory traversal detected. Access denied.")
    if any(sens in resolved_path for sens in SENSITIVE_FILES) or os.path.basename(resolved_path).startswith(".git"):
        raise HTTPException(status_code=403, detail="Access to sensitive files is strictly forbidden.")
    if not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(resolved_path, 'r', encoding='utf-8') as f:
        return {"content": f.read()}

@app.post("/write")
def write_file(path: str, content: FileContent):
    resolved_path = os.path.abspath(os.path.join(BASE_DIR, path))
    if not resolved_path.startswith(os.path.abspath(BASE_DIR)):
        raise HTTPException(status_code=403, detail="Directory traversal detected. Access denied.")
    if any(sens in resolved_path for sens in SENSITIVE_FILES) or os.path.basename(resolved_path).startswith(".git"):
        raise HTTPException(status_code=403, detail="Access to sensitive files is strictly forbidden.")
    os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
    with open(resolved_path, 'w', encoding='utf-8') as f:
        f.write(content.text)
    return {"status": "success"}
