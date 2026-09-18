from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config.database import Base, SessionLocal, engine
from app.config.security import hash_senha
from app.config.settings import ADMIN_EMAIL, ADMIN_SENHA, SECRET_KEY
from app.models.models import Usuario
from app.routers import anual, auth, competencias, dashboard, exportar, importador

app = FastAPI(title="CoreCast - Gestao de Atendimentos & SLA")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(importador.router)
app.include_router(dashboard.router)
app.include_router(anual.router)
app.include_router(competencias.router)
app.include_router(exportar.router)


@app.exception_handler(HTTPException)
async def redirecionar_nao_autenticado(request: Request, exc: HTTPException):
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return await http_exception_handler(request, exc)


@app.on_event("startup")
def iniciar_aplicacao():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Usuario).count() == 0:
            db.add(Usuario(
                nome="Administrador CoreCast",
                email=ADMIN_EMAIL.strip().lower(),
                senha_hash=hash_senha(ADMIN_SENHA),
                perfil="admin",
            ))
            db.commit()
    finally:
        db.close()


@app.get("/")
def raiz():
    return RedirectResponse("/dashboard", status_code=303)
