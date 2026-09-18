from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.security import exigir_login
from app.models.models import Competencia
from app.services.export_service import ExportService

router = APIRouter(prefix="/exportar", tags=["Exportacao"])


@router.get("/dados-rac")
def exportar_dados_rac(
    competencia_id: int,
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
):
    competencia = db.query(Competencia).filter(Competencia.id == competencia_id).first()
    if not competencia:
        raise HTTPException(status_code=404, detail="Competencia nao encontrada")

    conteudo, nome_arquivo = ExportService.gerar_dados_rac(db, competencia)
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
