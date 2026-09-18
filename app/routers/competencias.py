from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.security import exigir_login
from app.models.models import Competencia
from app.services.parsing_utils import MESES_PT
from app.templates_engine import templates

router = APIRouter(prefix="/competencias", tags=["Gestao de Bases"])


def _rotulo_para_ano_mes(ano_mes: str) -> str:
    ano, mes = ano_mes.split("-")
    nome_mes = MESES_PT[int(mes)].capitalize()
    return f"{nome_mes}/{ano}"


@router.get("")
def listar(request: Request, db: Session = Depends(get_db), usuario: dict = Depends(exigir_login)):
    competencias = db.query(Competencia).order_by(Competencia.ano_mes.desc()).all()
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request,
        "competencias.html",
        {"usuario": usuario, "competencias": competencias, "flash": flash},
    )


@router.post("")
def criar(
    request: Request,
    ano_mes: str = Form(...),
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
):
    existente = db.query(Competencia).filter(Competencia.ano_mes == ano_mes).first()
    if existente:
        request.session["flash"] = {"tipo": "erro", "mensagem": f"A competencia {ano_mes} ja existe."}
    else:
        db.add(Competencia(ano_mes=ano_mes, rotulo=_rotulo_para_ano_mes(ano_mes)))
        db.commit()
        request.session["flash"] = {"tipo": "sucesso", "mensagem": f"Competencia {ano_mes} criada com sucesso."}
    return RedirectResponse("/competencias", status_code=303)


@router.post("/{competencia_id}/status")
def alternar_status(
    request: Request,
    competencia_id: int,
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
):
    competencia = db.query(Competencia).filter(Competencia.id == competencia_id).first()
    if competencia:
        competencia.status = "Fechada" if competencia.status == "Aberta" else "Aberta"
        db.commit()
        request.session["flash"] = {"tipo": "sucesso", "mensagem": f"Competencia {competencia.rotulo} agora esta {competencia.status}."}
    return RedirectResponse("/competencias", status_code=303)


@router.post("/{competencia_id}/excluir")
def excluir(
    request: Request,
    competencia_id: int,
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
):
    competencia = db.query(Competencia).filter(Competencia.id == competencia_id).first()
    if competencia:
        rotulo = competencia.rotulo
        db.delete(competencia)
        db.commit()
        request.session["flash"] = {"tipo": "sucesso", "mensagem": f"Competencia {rotulo} e todos os dados vinculados foram excluidos."}
    return RedirectResponse("/competencias", status_code=303)
