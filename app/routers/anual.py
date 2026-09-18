from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.security import exigir_login
from app.models.models import BaselineTrimestral, Competencia, Incidente, Melhoria
from app.templates_engine import templates

router = APIRouter(prefix="/anual", tags=["Parametro Anual"])


def _trimestre_do_mes(mes: int) -> int:
    return (mes - 1) // 3 + 1


@router.get("")
def visao_anual(
    request: Request,
    ano: int | None = None,
    trimestre: int | None = None,
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
):
    todas_competencias = db.query(Competencia).order_by(Competencia.ano_mes.asc()).all()
    anos_disponiveis = sorted({int(c.ano_mes.split("-")[0]) for c in todas_competencias}, reverse=True)

    ano_atual = ano or (anos_disponiveis[0] if anos_disponiveis else date.today().year)
    competencias_ano = [c for c in todas_competencias if int(c.ano_mes.split("-")[0]) == ano_atual]
    competencias_ano.sort(key=lambda c: c.ano_mes)

    linhas_mensais = []
    por_trimestre = defaultdict(lambda: {"horas": 0.0, "incidentes": 0, "no_prazo": 0, "aging": 0, "reaberturas": 0})

    for c in competencias_ano:
        mes = int(c.ano_mes.split("-")[1])
        incidentes = db.query(Incidente).filter(Incidente.competencia_id == c.id).all()
        total_inc = len(incidentes)
        no_prazo = sum(1 for i in incidentes if i.status_sla == "No Prazo")
        aging_ok = sum(1 for i in incidentes if i.dentro_aging_8dias)
        reaberturas = sum(i.contagem_reaberturas or 0 for i in incidentes)

        eficiencia = round((no_prazo / total_inc) * 100, 2) if total_inc else 0.0
        aging_pct = round((aging_ok / total_inc) * 100, 2) if total_inc else 0.0
        reabertura_pct = round((reaberturas / total_inc) * 100, 2) if total_inc else 0.0

        linhas_mensais.append({
            "competencia": c,
            "mes": mes,
            "eficiencia_sla": eficiencia,
            "aging_pct": aging_pct,
            "reabertura_pct": reabertura_pct,
        })

        tri = _trimestre_do_mes(mes)
        acc = por_trimestre[tri]
        acc["horas"] += float(c.total_horas or 0)
        acc["incidentes"] += total_inc
        acc["no_prazo"] += no_prazo
        acc["aging"] += aging_ok
        acc["reaberturas"] += reaberturas

    resumo_trimestral = []
    for tri in range(1, 5):
        acc = por_trimestre.get(tri)
        if not acc or acc["incidentes"] == 0 and acc["horas"] == 0:
            resumo_trimestral.append({
                "trimestre": tri, "horas": 0.0, "incidentes": 0,
                "eficiencia_sla": 0.0, "aging_pct": 0.0, "reabertura_pct": 0.0,
            })
            continue
        total_inc = acc["incidentes"]
        resumo_trimestral.append({
            "trimestre": tri,
            "horas": round(acc["horas"], 2),
            "incidentes": total_inc,
            "eficiencia_sla": round((acc["no_prazo"] / total_inc) * 100, 2) if total_inc else 0.0,
            "aging_pct": round((acc["aging"] / total_inc) * 100, 2) if total_inc else 0.0,
            "reabertura_pct": round((acc["reaberturas"] / total_inc) * 100, 2) if total_inc else 0.0,
        })

    trimestre_atual = trimestre or (_trimestre_do_mes(date.today().month) if ano_atual == date.today().year else 1)
    chave_trimestre = f"{ano_atual}-Q{trimestre_atual}"

    baseline = db.query(BaselineTrimestral).filter(BaselineTrimestral.trimestre == chave_trimestre).first()
    saldo_anterior = float(baseline.saldo_anterior) if baseline else 0.0

    meses_do_trimestre = [m for m in range(1, 13) if _trimestre_do_mes(m) == trimestre_atual]
    competencias_trimestre_ids = [
        c.id for c in competencias_ano if int(c.ano_mes.split("-")[1]) in meses_do_trimestre
    ]
    horas_estimadas_periodo = 0.0
    melhorias_periodo = []
    if competencias_trimestre_ids:
        melhorias_periodo = (
            db.query(Melhoria)
            .filter(Melhoria.competencia_id.in_(competencias_trimestre_ids))
            .order_by(Melhoria.id.desc())
            .all()
        )
        horas_estimadas_periodo = sum(float(m.horas_estimadas or 0) for m in melhorias_periodo)

    saldo_atualizado = max(0.0, saldo_anterior - horas_estimadas_periodo)

    grafico_evolucao = {
        "labels": [f"{l['mes']:02d}/{ano_atual}" for l in linhas_mensais],
        "eficiencia_sla": [l["eficiencia_sla"] for l in linhas_mensais],
        "aging_pct": [l["aging_pct"] for l in linhas_mensais],
        "total_horas": [float(l["competencia"].total_horas or 0) for l in linhas_mensais],
    }

    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "anual.html", {
        "usuario": usuario,
        "flash": flash,
        "anos_disponiveis": anos_disponiveis,
        "ano_atual": ano_atual,
        "linhas_mensais": linhas_mensais,
        "resumo_trimestral": resumo_trimestral,
        "trimestre_atual": trimestre_atual,
        "chave_trimestre": chave_trimestre,
        "saldo_anterior": round(saldo_anterior, 2),
        "horas_estimadas_periodo": round(horas_estimadas_periodo, 2),
        "saldo_atualizado": round(saldo_atualizado, 2),
        "grafico_evolucao": grafico_evolucao,
        "melhorias_periodo": melhorias_periodo,
        "competencias_trimestre": [c for c in competencias_ano if c.id in competencias_trimestre_ids],
    })


@router.post("/baseline")
def atualizar_baseline(
    request: Request,
    trimestre: str = Form(...),
    saldo_anterior: float = Form(...),
    ano: int = Form(...),
    trimestre_num: int = Form(...),
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
):
    baseline = db.query(BaselineTrimestral).filter(BaselineTrimestral.trimestre == trimestre).first()
    if baseline:
        baseline.saldo_anterior = saldo_anterior
    else:
        baseline = BaselineTrimestral(trimestre=trimestre, saldo_anterior=saldo_anterior)
        db.add(baseline)
    db.commit()
    request.session["flash"] = {"tipo": "sucesso", "mensagem": f"Saldo anterior do trimestre {trimestre} atualizado."}
    return RedirectResponse(f"/anual?ano={ano}&trimestre={trimestre_num}", status_code=303)


@router.post("/melhorias")
def criar_melhoria(
    request: Request,
    competencia_id: int = Form(...),
    ritm_numero: str = Form(""),
    aplicacao: str = Form(""),
    descricao: str = Form(""),
    horas_estimadas: float = Form(0),
    status: str = Form("Em Andamento"),
    solicitante: str = Form(""),
    ano: int = Form(...),
    trimestre_num: int = Form(...),
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
):
    competencia = db.query(Competencia).filter(Competencia.id == competencia_id).first()
    if competencia:
        db.add(Melhoria(
            competencia_id=competencia.id,
            ritm_numero=ritm_numero or None,
            aplicacao=aplicacao or None,
            descricao=descricao or None,
            horas_estimadas=horas_estimadas,
            status=status,
            solicitante=solicitante or None,
        ))
        competencia.total_melhorias = (competencia.total_melhorias or 0) + 1
        db.commit()
        request.session["flash"] = {"tipo": "sucesso", "mensagem": "Melhoria registrada no baseline do periodo."}
    return RedirectResponse(f"/anual?ano={ano}&trimestre={trimestre_num}", status_code=303)


@router.post("/melhorias/{melhoria_id}/excluir")
def excluir_melhoria(
    request: Request,
    melhoria_id: int,
    ano: int = Form(...),
    trimestre_num: int = Form(...),
    db: Session = Depends(get_db),
    usuario: dict = Depends(exigir_login),
):
    melhoria = db.query(Melhoria).filter(Melhoria.id == melhoria_id).first()
    if melhoria:
        competencia = db.query(Competencia).filter(Competencia.id == melhoria.competencia_id).first()
        db.delete(melhoria)
        if competencia and competencia.total_melhorias:
            competencia.total_melhorias = max(0, competencia.total_melhorias - 1)
        db.commit()
        request.session["flash"] = {"tipo": "sucesso", "mensagem": "Melhoria removida do baseline do periodo."}
    return RedirectResponse(f"/anual?ano={ano}&trimestre={trimestre_num}", status_code=303)
