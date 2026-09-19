import re
import unicodedata
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.security import exigir_login
from app.config.settings import (
    LIMITE_REPASSE_N2_MINUTOS,
    SLA_META_AGING_PERCENTUAL,
    SLA_META_EFICIENCIA_PERCENTUAL,
    SLA_META_REABERTURA_PERCENTUAL,
)
from app.models.models import Competencia, HorasTereos, Incidente, Requisicao
from app.services.parsing_utils import parse_prioridade_num
from app.templates_engine import templates

router = APIRouter(prefix="/dashboard", tags=["Dashboard Mensal"])

SEM_APLICACAO = "Sem aplicacao"
ESTADOS_ENCERRADOS = ("encerrado", "resolvido", "fechado")
LIMITE_APLICACOES = 10


def _top(contagem: dict, limite: int = LIMITE_APLICACOES) -> dict:
    chaves = sorted(contagem, key=lambda k: -contagem[k])[:limite]
    return {"labels": chaves, "valores": [round(contagem[k], 2) for k in chaves]}


STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "um", "uma", "e", "ou",
    "com", "sem", "para", "por", "que", "se", "ao", "ja", "nao", "mais", "the", "of", "to", "in", "is", "and",
    "for", "on", "not", "after", "sistema", "erro", "falha", "falhas", "problema", "favor", "ao", "pelo", "pela", "esta", "estao",
}
NIVEL_ALTA_PCT = 10.0
NIVEL_MODERADA_PCT = 3.0


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()


def _termos(descricao: str) -> list[tuple[str, str]]:
    """Palavras relevantes de uma descricao como (chave_sem_acento, forma_original)."""
    termos = []
    for palavra in re.findall(r"[^\W\d_]{3,}", descricao.lower()):
        chave = _sem_acento(palavra)
        if chave not in STOPWORDS:
            termos.append((chave, palavra))
    return termos


def _falhas_recorrentes(descricoes: list[str], maximo: int = 2) -> list[dict]:
    """Temas mais recorrentes nas descricoes (bigramas; palavras soltas se nao houver bigrama repetido)."""
    docs = [_termos(d) for d in descricoes if d]
    rotulos: dict[str, str] = {}
    contagens: dict[int, Counter] = {1: Counter(), 2: Counter()}
    for termos in docs:
        vistos = set()
        for n in (1, 2):
            for k in range(len(termos) - n + 1):
                grupo = termos[k:k + n]
                chave = " ".join(t[0] for t in grupo)
                vistos.add((n, chave))
                rotulos.setdefault(chave, " ".join(t[1] for t in grupo))
        for n, chave in vistos:
            contagens[n][chave] += 1

    escolhidos: list[dict] = []
    usados: set[str] = set()
    for n in (2, 1):
        for chave, qtd in contagens[n].most_common():
            if qtd < 2 or len(escolhidos) >= maximo:
                break
            partes = set(chave.split())
            if partes & usados:
                continue
            usados |= partes
            escolhidos.append({"texto": rotulos[chave].capitalize(), "qtd": qtd})
    if not escolhidos and descricoes:
        primeira = next((d for d in descricoes if d), "")
        escolhidos.append({"texto": primeira[:90] + ("..." if len(primeira) > 90 else ""), "qtd": 1})
    return escolhidos


def _ranking_aplicacoes(incidentes, horas) -> dict:
    total = len(incidentes)
    por_app: dict[str, list] = defaultdict(list)
    for i in incidentes:
        if i.business_application:
            por_app[i.business_application].append(i)

    horas_por_chamado = defaultdict(float)
    for h in horas:
        if h.chamado_associado:
            horas_por_chamado[h.chamado_associado] += float(h.horas or 0)

    ordenadas = sorted(por_app, key=lambda a: (-len(por_app[a]), a))[:6]
    ranking = []
    for pos, app in enumerate(ordenadas, start=1):
        itens = por_app[app]
        pct = len(itens) / total * 100 if total else 0
        ranking.append({
            "posicao": pos,
            "aplicacao": app,
            "chamados": len(itens),
            "horas": round(sum(horas_por_chamado.get(i.numero, 0) for i in itens), 1),
            "pct": round(pct, 1),
            "nivel": "Alta" if pct >= NIVEL_ALTA_PCT else "Moderada" if pct >= NIVEL_MODERADA_PCT else "Estavel",
            "falhas": _falhas_recorrentes([i.descricao_resumida for i in itens]),
        })
    return {"podio": ranking[:3], "demais": ranking[3:], "maior": ranking[3]["chamados"] if len(ranking) > 3 else 0}


def _diagnostico_fluxo(incidentes) -> dict:
    """Incidentes repassados N1 -> N2 com tempo acima do limite (padrao 30 min).

    Formula: atrasados = COUNT(tempo_repasse_minutos > limite); impacto = atrasados / total * 100.
    Incidentes sem o dado de repasse nao entram na contagem de atrasados.
    """
    total = len(incidentes)
    com_dado = [i for i in incidentes if i.tempo_repasse_minutos is not None]
    atrasados = [i for i in com_dado if float(i.tempo_repasse_minutos) > LIMITE_REPASSE_N2_MINUTOS]
    por_prioridade = defaultdict(int)
    for i in atrasados:
        por_prioridade[parse_prioridade_num(i.prioridade)] += 1
    detalhe = [{"rotulo": f"P{p}", "qtd": por_prioridade[p]} for p in sorted(por_prioridade)]
    return {
        "disponivel": bool(com_dado),
        "limite": int(LIMITE_REPASSE_N2_MINUTOS) if float(LIMITE_REPASSE_N2_MINUTOS).is_integer() else LIMITE_REPASSE_N2_MINUTOS,
        "total": total,
        "atrasados": len(atrasados),
        "pct": round(len(atrasados) / total * 100) if total else 0,
        "detalhe": detalhe,
        "soma": " + ".join(str(d["qtd"]) for d in detalhe),
    }


def _montar_graficos(incidentes, requisicoes, horas) -> dict:
    app_por_chamado = {i.numero: i.business_application for i in incidentes}
    app_por_chamado.update({r.numero: r.business_application for r in requisicoes})
    melhorias = {r.numero for r in requisicoes if "melhoria" in (r.classificacao_demanda or "").lower()}

    horas_app = defaultdict(float)
    horas_classe = {"Requisicoes": 0.0, "Melhorias": 0.0, "Incidentes": 0.0, "Outras filas": 0.0, "Sem chamado": 0.0}
    for h in horas:
        valor = float(h.horas or 0)
        chamado = h.chamado_associado
        horas_app[app_por_chamado.get(chamado) or SEM_APLICACAO] += valor
        if not chamado:
            horas_classe["Sem chamado"] += valor
        elif chamado.startswith("INC"):
            horas_classe["Incidentes"] += valor
        elif chamado.startswith("RITM"):
            horas_classe["Melhorias" if chamado in melhorias else "Requisicoes"] += valor
        else:
            horas_classe["Outras filas"] += valor

    atend_app = defaultdict(int)
    for chamado in [*incidentes, *requisicoes]:
        atend_app[chamado.business_application or SEM_APLICACAO] += 1

    por_squad = defaultdict(lambda: {"total": 0, "no_prazo": 0})
    for i in incidentes:
        squad = por_squad[i.grupo_atribuicao or "Nao informado"]
        squad["total"] += 1
        if (i.estado or "").lower() in ESTADOS_ENCERRADOS and i.status_sla == "No Prazo":
            squad["no_prazo"] += 1
    squads = sorted(por_squad, key=lambda k: -por_squad[k]["total"])

    return {
        "graf_horas_app": _top(horas_app),
        "graf_classificacao": {
            "labels": list(horas_classe),
            "valores": [round(v, 2) for v in horas_classe.values()],
        },
        "graf_atend_app": _top(atend_app),
        "graf_squad": {
            "labels": squads,
            "total": [por_squad[k]["total"] for k in squads],
            "no_prazo": [por_squad[k]["no_prazo"] for k in squads],
        },
    }


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
            "graf_horas_app": {"labels": [], "valores": []},
            "graf_classificacao": {"labels": [], "valores": []},
            "graf_atend_app": {"labels": [], "valores": []},
            "graf_squad": {"labels": [], "total": [], "no_prazo": []},
            "fluxo": None,
            "ranking": None,
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

    requisicoes = db.query(Requisicao).filter(Requisicao.competencia_id == competencia.id).all()
    graficos = _montar_graficos(incidentes, requisicoes, horas)

    contexto.update({
        **graficos,
        "fluxo": _diagnostico_fluxo(incidentes),
        "ranking": _ranking_aplicacoes(incidentes, horas),
        "cards": cards,
        "sla_prioridade": sla_prioridade,
        "sla_pizza": sla_pizza,
        "horas_grupo": horas_grupo,
        "top_atrasados": top_atrasados,
    })
    return templates.TemplateResponse(request, "dashboard.html", contexto)
