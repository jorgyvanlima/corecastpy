from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.security import exigir_login
from app.config.settings import (
    SLA_META_AGING_PERCENTUAL,
    SLA_META_EFICIENCIA_PERCENTUAL,
    SLA_META_REABERTURA_PERCENTUAL,
)
from app.models.models import Competencia, HorasTereos, Incidente
from app.templates_engine import templates

router = APIRouter(prefix="/dashboard", tags=["Dashboard Mensal"])


@router.get("")
def dashboard(request: Request, competencia_id: int | None = None, db: Session = Depends(get_db), usuario: dict = Depends(exigir_login)):
    competencias = db.query(Competencia).order_by(Competencia.ano_mes.desc()).all()

    competencia = None
    if competencia_id:
        competencia = db.query(Competencia).filter(Competencia.id == competencia_id).first()
    if not competencia and competencias:
        competencia = competencias[0]

    contexto = {
        "usuario": usuario,
        "competencias": competencias,
        "competencia": competencia,
        "meta_eficiencia": SLA_META_EFICIENCIA_PERCENTUAL,
        "meta_aging": SLA_META_AGING_PERCENTUAL,
        "meta_reabertura": SLA_META_REABERTURA_PERCENTUAL,
    }

    if not competencia:
        contexto.update({
            "cards": None,
            "sla_prioridade": {"labels": [], "no_prazo": [], "atraso": []},
            "sla_pizza": {"labels": [], "valores": []},
            "horas_grupo": {"labels": [], "valores": []},
            "top_atrasados": [],
        })
        return templates.TemplateResponse(request, "dashboard.html", contexto)

    incidentes = db.query(Incidente).filter(Incidente.competencia_id == competencia.id).all()
    horas = db.query(HorasTereos).filter(HorasTereos.competencia_id == competencia.id).all()

    total_incidentes = len(incidentes)
    no_prazo = sum(1 for i in incidentes if i.status_sla == "No Prazo")
    dentro_aging = sum(1 for i in incidentes if i.dentro_aging_8dias)
    soma_reaberturas = sum(i.contagem_reaberturas or 0 for i in incidentes)
    total_horas = sum(float(h.horas or 0) for h in horas)

    eficiencia_sla = round((no_prazo / total_incidentes) * 100, 2) if total_incidentes else 0.0
    aging_pct = round((dentro_aging / total_incidentes) * 100, 2) if total_incidentes else 0.0
    taxa_reabertura = round((soma_reaberturas / total_incidentes) * 100, 2) if total_incidentes else 0.0

    cards = {
        "eficiencia_sla": eficiencia_sla,
        "aging_pct": aging_pct,
        "taxa_reabertura": taxa_reabertura,
        "total_horas": round(total_horas, 2),
        "total_incidentes": total_incidentes,
        "total_requisicoes": competencia.total_requisicoes,
    }

    por_prioridade = defaultdict(lambda: {"no_prazo": 0, "atraso": 0})
    for i in incidentes:
        chave = i.prioridade or "Nao informado"
        if i.status_sla == "No Prazo":
            por_prioridade[chave]["no_prazo"] += 1
        else:
            por_prioridade[chave]["atraso"] += 1
    labels_prioridade = sorted(por_prioridade.keys())
    sla_prioridade = {
        "labels": labels_prioridade,
        "no_prazo": [por_prioridade[k]["no_prazo"] for k in labels_prioridade],
        "atraso": [por_prioridade[k]["atraso"] for k in labels_prioridade],
    }

    sla_pizza = {
        "labels": ["No Prazo", "Atraso"],
        "valores": [no_prazo, total_incidentes - no_prazo],
    }

    horas_por_grupo = defaultdict(float)
    for h in horas:
        chave = h.grupo_atribuicao or "Nao informado"
        horas_por_grupo[chave] += float(h.horas or 0)
    labels_grupo = sorted(horas_por_grupo.keys(), key=lambda k: -horas_por_grupo[k])[:10]
    horas_grupo = {
        "labels": labels_grupo,
        "valores": [round(horas_por_grupo[k], 2) for k in labels_grupo],
    }

    top_atrasados = sorted(
        [i for i in incidentes if i.status_sla == "Atraso"],
        key=lambda i: float(i.duracao_horas or 0) - float(i.meta_sla_horas or 0),
        reverse=True,
    )[:10]

    contexto.update({
        "cards": cards,
        "sla_prioridade": sla_prioridade,
        "sla_pizza": sla_pizza,
        "horas_grupo": horas_grupo,
        "top_atrasados": top_atrasados,
    })
    return templates.TemplateResponse(request, "dashboard.html", contexto)
