from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.security import exigir_login
from app.models.models import Competencia
from app.services.import_service import FileImportService
from app.services.parsing_utils import MESES_PT
from app.templates_engine import templates

router = APIRouter(prefix="/importar", tags=["Importacao"])


def _rotulo_para_ano_mes(ano_mes: str) -> str:
    ano, mes = ano_mes.split("-")
    nome_mes = MESES_PT[int(mes)].capitalize()
    return f"{nome_mes}/{ano}"


@router.get("")
def form_importar(request: Request, db: Session = Depends(get_db), usuario: dict = Depends(exigir_login)):
    competencias = db.query(Competencia).order_by(Competencia.ano_mes.desc()).all()
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request,
        "importar.html",
        {"usuario": usuario, "competencias": competencias, "flash": flash},
    )


@router.post("")
def processar_importacao(
    request: Request,
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
    competencia_id: str = Form(""),
    nova_competencia_ano_mes: str = Form(""),
    horas_file: UploadFile = File(None),
    inc_file: UploadFile = File(None),
    req_file: UploadFile = File(None),
    rac_file: UploadFile = File(None),
):
    competencia = None
    if nova_competencia_ano_mes:
        competencia = db.query(Competencia).filter(Competencia.ano_mes == nova_competencia_ano_mes).first()
        if not competencia:
            competencia = Competencia(
                ano_mes=nova_competencia_ano_mes,
                rotulo=_rotulo_para_ano_mes(nova_competencia_ano_mes),
            )
            db.add(competencia)
            db.commit()
            db.refresh(competencia)
    elif competencia_id:
        competencia = db.query(Competencia).filter(Competencia.id == int(competencia_id)).first()

    if not competencia:
        request.session["flash"] = {"tipo": "erro", "mensagem": "Selecione ou informe uma competencia valida."}
        return RedirectResponse("/importar", status_code=303)

    resultado = FileImportService.process_import(
        db=db,
        competencia=competencia,
        horas_file=horas_file,
        inc_file=inc_file,
        req_file=req_file,
        rac_file=rac_file,
    )

    request.session["flash"] = {
        "tipo": "sucesso",
        "mensagem": (
            f"Importacao concluida para {competencia.rotulo}: "
            f"{resultado['horas']} horas, {resultado['incidentes']} incidentes, "
            f"{resultado['requisicoes']} requisicoes."
        ),
        "avisos": resultado["avisos"],
    }
    return RedirectResponse(f"/dashboard?competencia_id={competencia.id}", status_code=303)
