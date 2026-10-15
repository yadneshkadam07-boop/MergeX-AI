from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import tasks, users

app = FastAPI(title="Taskly API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
