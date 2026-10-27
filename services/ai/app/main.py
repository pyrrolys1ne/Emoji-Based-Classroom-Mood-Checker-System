from fastapi import FastAPI

app = FastAPI(title="Classroom Mood AI Service", version="0.1.0")


@app.get("/health")
def health():
    return {"code": "OK", "message": "成功", "data": {"status": "ok", "stage": "scaffold", "modelLoaded": False}}
