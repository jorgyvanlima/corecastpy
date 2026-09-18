from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.security import verificar_senha
from app.models.models import Usuario
from app.templates_engine import templates

router = APIRouter(tags=["Autenticacao"])


@router.get("/login")
def login_form(request: Request):
    if request.session.get("usuario"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"erro": None})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    db: Session = Depends(get_db),
):
    usuario = db.query(Usuario).filter(Usuario.email == email.strip().lower(), Usuario.ativo.is_(True)).first()
    if not usuario or not verificar_senha(senha, usuario.senha_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"erro": "Credenciais invalidas ou usuario inativo."},
            status_code=401,
        )
    request.session["usuario"] = {"id": usuario.id, "nome": usuario.nome, "email": usuario.email, "perfil": usuario.perfil}
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
