"""Pipeline de importacao das bases mensais (Horas Tereos, Incidentes,
Requisicoes e, opcionalmente, o consolidado Dados_RAC).

Implementa as regras de precisao matematica descritas nas instrucoes do
projeto: leitura por nome de cabecalho, filtro de competencia, cruzamento
deterministico via regex e normalizacao de grupo de atribuicao.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import Competencia, HorasTereos, Incidente, Requisicao
from app.services.parsing_utils import (
    calcular_aging,
    calcular_duracao_horas,
    calcular_meta_sla,
    calcular_status_sla,
    extrair_chamado,
    iteration_path_pertence_competencia,
    map_columns,
    normalize_text,
    normalizar_grupo_atribuicao,
    safe_datetime,
    safe_float,
    safe_int,
    safe_str,
)

HORAS_COLS = {
    "title": ["title", "titulo", "título"],
    "work_item_id": ["id", "work item id", "item id", "workitem id"],
    "work_item_type": ["work item type", "tipo", "type"],
    "assigned_to": ["assigned to", "atribuido a", "atribuído a", "responsavel", "responsável"],
    "state": ["state", "estado"],
    "grupo_atribuicao": ["area path", "team", "grupo de atribuicao", "grupo de atribuição", "assignment group"],
    "horas": ["effort", "completed work", "horas", "esforco", "esforço"],
    "iteration_path": ["iteration path", "iteration", "sprint"],
}

INC_COLS = {
    "numero": ["number", "numero", "número"],
    "criado_em": ["opened", "criado em", "created", "data de abertura"],
    "estado": ["state", "estado"],
    "atribuicao_a": ["assigned to", "atribuido a", "atribuído a"],
    "grupo_atribuicao": ["assignment group", "grupo de atribuicao", "grupo de atribuição"],
    "business_application": ["business application", "aplicacao de negocio", "aplicação de negócio"],
    "data_ultimo_comentario": ["updated", "data do ultimo comentario", "data do último comentário", "last updated"],
    "prioridade": ["priority", "prioridade"],
    "duracao_segundos": ["duration", "duracao", "duração"],
    "duracao_negocios_segundos": [
        "business duration", "duracao de negocios", "duração de negócios", "business duration (seconds)",
    ],
    "duracao_horas": ["duration (hours)", "duracao horas", "duração horas", "horas de duracao"],
    "contagem_reaberturas": ["reopen count", "reaberturas", "contagem de reaberturas"],
    "descricao_resumida": ["short description", "descricao resumida", "descrição resumida"],
}

REQ_COLS = {
    "numero": ["number", "numero", "número"],
    "classificacao_demanda": [
        "request classification", "classificacao da demanda", "classificação da demanda", "classification",
    ],
    "complexidade_demanda": ["complexity", "complexidade", "complexidade da demanda"],
    "criacao_em": ["opened", "created", "criado em", "data de abertura"],
    "estado": ["state", "estado"],
    "grupo_atribuicao": ["assignment group", "grupo de atribuicao", "grupo de atribuição"],
    "atribuicao_a": ["assigned to", "atribuido a", "atribuído a"],
    "business_application": ["business application", "aplicacao de negocio", "aplicação de negócio"],
    "horas_consumidas": ["horas consumidas", "effort", "horas"],
}


def _read_tabular(upload_file) -> Optional[pd.DataFrame]:
    if upload_file is None or not getattr(upload_file, "filename", None):
        return None
    nome = upload_file.filename.lower()
    upload_file.file.seek(0)
    if nome.endswith(".csv"):
        return pd.read_csv(upload_file.file, sep=None, engine="python")
    return pd.read_excel(upload_file.file)


def _match_rac_sheets(sheets: dict):
    df_horas = df_inc = df_req = None
    restantes = []
    for nome_aba, df in sheets.items():
        chave = normalize_text(nome_aba)
        if "hora" in chave or "tereos" in chave or "devops" in chave:
            df_horas = df
        elif "inc" in chave:
            df_inc = df
        elif "req" in chave or "ritm" in chave:
            df_req = df
        else:
            restantes.append(df)

    abas_ordenadas = list(sheets.values())
    if df_horas is None and len(abas_ordenadas) > 0:
        df_horas = abas_ordenadas[0]
    if df_inc is None and len(abas_ordenadas) > 1:
        df_inc = abas_ordenadas[1]
    if df_req is None and len(abas_ordenadas) > 2:
        df_req = abas_ordenadas[2]
    return df_horas, df_inc, df_req


def _atualizar_totais_competencia(db: Session, competencia: Competencia) -> None:
    total_horas = db.query(HorasTereos).filter(HorasTereos.competencia_id == competencia.id)
    soma_horas = sum(float(h.horas or 0) for h in total_horas)

    incidentes = db.query(Incidente).filter(Incidente.competencia_id == competencia.id).all()
    total_incidentes = len(incidentes)
    no_prazo = sum(1 for i in incidentes if i.status_sla == "No Prazo")
    sla_cumprimento = round((no_prazo / total_incidentes) * 100, 2) if total_incidentes else 0.0

    total_requisicoes = db.query(Requisicao).filter(Requisicao.competencia_id == competencia.id).count()

    competencia.total_horas = round(soma_horas, 2)
    competencia.total_incidentes = total_incidentes
    competencia.total_requisicoes = total_requisicoes
    competencia.sla_cumprimento = sla_cumprimento
    db.add(competencia)
    db.commit()


class FileImportService:
    @staticmethod
    def process_import(
        db: Session,
        competencia: Competencia,
        horas_file=None,
        inc_file=None,
        req_file=None,
        rac_file=None,
    ) -> dict:
        resultado = {"horas": 0, "incidentes": 0, "requisicoes": 0, "avisos": []}

        # 1. Limpeza idempotente da competencia antes de reimportar.
        db.query(HorasTereos).filter(HorasTereos.competencia_id == competencia.id).delete()
        db.query(Incidente).filter(Incidente.competencia_id == competencia.id).delete()
        db.query(Requisicao).filter(Requisicao.competencia_id == competencia.id).delete()
        db.commit()

        df_horas = df_inc = df_req = None

        if rac_file is not None and getattr(rac_file, "filename", None):
            rac_file.file.seek(0)
            abas = pd.read_excel(rac_file.file, sheet_name=None)
            df_horas, df_inc, df_req = _match_rac_sheets(abas)
            resultado["avisos"].append(
                "Consolidado Dados_RAC detectado: possui precedencia sobre os arquivos brutos enviados."
            )

        if df_horas is None:
            df_horas = _read_tabular(horas_file)
        if df_inc is None:
            df_inc = _read_tabular(inc_file)
        if df_req is None:
            df_req = _read_tabular(req_file)

        ano_str, mes_str = competencia.ano_mes.split("-")
        ano, mes = int(ano_str), int(mes_str)

        horas_por_chamado: dict[str, float] = {}

        # 2. Horas Tereos — filtro de competencia + cruzamento deterministico.
        if df_horas is not None and not df_horas.empty:
            df_map = map_columns(df_horas, HORAS_COLS)
            registros = []
            for _, row in df_map.iterrows():
                iteration_path = safe_str(row.get("iteration_path"))
                if not iteration_path_pertence_competencia(iteration_path, ano, mes):
                    continue
                title = safe_str(row.get("title"))
                chamado = extrair_chamado(title)
                horas_valor = safe_float(row.get("horas"))
                registros.append(
                    HorasTereos(
                        competencia_id=competencia.id,
                        title=title,
                        work_item_id=safe_str(row.get("work_item_id")),
                        work_item_type=safe_str(row.get("work_item_type")),
                        assigned_to=safe_str(row.get("assigned_to")),
                        state=safe_str(row.get("state")),
                        grupo_atribuicao=normalizar_grupo_atribuicao(safe_str(row.get("grupo_atribuicao"))),
                        horas=horas_valor,
                        iteration_path=iteration_path,
                        chamado_associado=chamado,
                    )
                )
                if chamado:
                    horas_por_chamado[chamado] = round(horas_por_chamado.get(chamado, 0.0) + horas_valor, 2)
            if registros:
                db.bulk_save_objects(registros)
            resultado["horas"] = len(registros)
        else:
            resultado["avisos"].append("Arquivo de Horas Tereos nao informado ou vazio para esta competencia.")

        # 3. Incidentes — calculo de SLA e aging.
        if df_inc is not None and not df_inc.empty:
            df_map = map_columns(df_inc, INC_COLS)
            registros = []
            for _, row in df_map.iterrows():
                numero = safe_str(row.get("numero"))
                if not numero:
                    continue
                numero = numero.upper()
                prioridade = safe_str(row.get("prioridade"))
                meta_sla = calcular_meta_sla(prioridade)
                duracao_horas = calcular_duracao_horas(
                    duracao_segundos=safe_int(row.get("duracao_segundos")),
                    duracao_negocios_segundos=safe_int(row.get("duracao_negocios_segundos")),
                    duracao_horas_informada=safe_float(row.get("duracao_horas")),
                )
                registros.append(
                    Incidente(
                        competencia_id=competencia.id,
                        numero=numero,
                        criado_em=safe_datetime(row.get("criado_em")),
                        estado=safe_str(row.get("estado")) or "Encerrado",
                        atribuicao_a=safe_str(row.get("atribuicao_a")),
                        grupo_atribuicao=normalizar_grupo_atribuicao(safe_str(row.get("grupo_atribuicao"))),
                        business_application=safe_str(row.get("business_application")),
                        data_ultimo_comentario=safe_datetime(row.get("data_ultimo_comentario")),
                        prioridade=prioridade,
                        duracao_segundos=safe_int(row.get("duracao_segundos")),
                        duracao_negocios_segundos=safe_int(row.get("duracao_negocios_segundos")),
                        duracao_horas=duracao_horas,
                        meta_sla_horas=meta_sla,
                        status_sla=calcular_status_sla(duracao_horas, meta_sla),
                        dentro_aging_8dias=calcular_aging(duracao_horas),
                        contagem_reaberturas=safe_int(row.get("contagem_reaberturas")),
                        horas_consumidas=horas_por_chamado.get(numero, 0.0),
                        descricao_resumida=safe_str(row.get("descricao_resumida")),
                    )
                )
            if registros:
                db.bulk_save_objects(registros)
            resultado["incidentes"] = len(registros)
        else:
            resultado["avisos"].append("Arquivo de Incidentes nao informado ou vazio para esta competencia.")

        # 4. Requisicoes.
        if df_req is not None and not df_req.empty:
            df_map = map_columns(df_req, REQ_COLS)
            registros = []
            for _, row in df_map.iterrows():
                numero = safe_str(row.get("numero"))
                if not numero:
                    continue
                numero = numero.upper()
                horas_informadas = safe_float(row.get("horas_consumidas"))
                registros.append(
                    Requisicao(
                        competencia_id=competencia.id,
                        numero=numero,
                        classificacao_demanda=safe_str(row.get("classificacao_demanda")),
                        complexidade_demanda=safe_str(row.get("complexidade_demanda")),
                        criacao_em=safe_datetime(row.get("criacao_em")),
                        estado=safe_str(row.get("estado")),
                        grupo_atribuicao=normalizar_grupo_atribuicao(safe_str(row.get("grupo_atribuicao"))),
                        atribuicao_a=safe_str(row.get("atribuicao_a")),
                        business_application=safe_str(row.get("business_application")),
                        horas_consumidas=horas_por_chamado.get(numero, horas_informadas),
                    )
                )
            if registros:
                db.bulk_save_objects(registros)
            resultado["requisicoes"] = len(registros)
        else:
            resultado["avisos"].append("Arquivo de Requisicoes nao informado ou vazio para esta competencia.")

        db.commit()
        _atualizar_totais_competencia(db, competencia)
        return resultado
