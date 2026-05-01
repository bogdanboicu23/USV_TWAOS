from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import autentificare, sarcini


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Gestionar de Sarcini",
    description="API pentru gestionarea sarcinilor — TAOS Labs 02-05",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(autentificare.router)
app.include_router(sarcini.router)


@app.get("/healthz")
def health_check():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
