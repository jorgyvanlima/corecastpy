"""Geracao da planilha oficial consolidada Dados_RAC_XX-XXXX.xlsx."""
from __future__ import annotations

import io

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import Competencia, HorasTereos, Incidente, Melhoria, Requisicao

HEADER_FORMAT = {
    "bold": True,
    "bg_color": "#1B2A4A",
    "font_color": "#FFFFFF",
    "border": 1,
}


class ExportService:
    @staticmethod
    def gerar_dados_rac(db: Session, competencia: Competencia) -> tuple[bytes, str]:
        horas = db.query(HorasTereos).filter(HorasTereos.competencia_id == competencia.id).all()
        incidentes = db.query(Incidente).filter(Incidente.competencia_id == competencia.id).all()
        requisicoes = db.query(Requisicao).filter(Requisicao.competencia_id == competencia.id).all()
        melhorias = db.query(Melhoria).filter(Melhoria.competencia_id == competencia.id).all()

        df_horas = pd.DataFrame([{
            "Title": h.title,
            "Work Item ID": h.work_item_id,
            "Work Item Type": h.work_item_type,
            "Assigned To": h.assigned_to,
            "State": h.state,
            "Grupo de Atribuicao": h.grupo_atribuicao,
            "Effort (Horas)": float(h.horas or 0),
            "Iteration Path": h.iteration_path,
            "Chamado Associado": h.chamado_associado,
        } for h in horas])

        df_inc = pd.DataFrame([{
            "Numero": i.numero,
            "Criado em": i.criado_em,
            "Estado": i.estado,
            "Atribuicao a": i.atribuicao_a,
            "Grupo de Atribuicao": i.grupo_atribuicao,
            "Business Application": i.business_application,
            "Prioridade": i.prioridade,
            "Duracao (Horas)": float(i.duracao_horas or 0),
            "Meta SLA (Horas)": float(i.meta_sla_horas or 0),
            "Status SLA": i.status_sla,
            "Dentro Aging 8 Dias": i.dentro_aging_8dias,
            "Reaberturas": i.contagem_reaberturas,
            "Horas Consumidas": float(i.horas_consumidas or 0),
        } for i in incidentes])

        df_req = pd.DataFrame([{
            "Numero": r.numero,
            "Classificacao da Demanda": r.classificacao_demanda,
            "Complexidade": r.complexidade_demanda,
            "Criacao em": r.criacao_em,
            "Estado": r.estado,
            "Grupo de Atribuicao": r.grupo_atribuicao,
            "Atribuicao a": r.atribuicao_a,
            "Business Application": r.business_application,
            "Horas Consumidas": float(r.horas_consumidas or 0),
        } for r in requisicoes])

        df_melh = pd.DataFrame([{
            "RITM": m.ritm_numero,
            "Aplicacao": m.aplicacao,
            "Descricao": m.descricao,
            "Horas Estimadas": float(m.horas_estimadas or 0),
            "Horas Consumidas": float(m.horas_consumidas or 0),
            "Status": m.status,
            "Solicitante": m.solicitante,
        } for m in melhorias])

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            planilhas = {
                "Horas Tereos": df_horas,
                "Incidentes": df_inc,
                "Requisicoes": df_req,
                "Melhorias": df_melh,
            }
            workbook = writer.book
            header_fmt = workbook.add_format(HEADER_FORMAT)

            for nome_aba, df in planilhas.items():
                if df.empty:
                    df = pd.DataFrame({"Sem dados": []})
                df.to_excel(writer, sheet_name=nome_aba, index=False, startrow=1, header=False)
                worksheet = writer.sheets[nome_aba]
                for col_idx, col_name in enumerate(df.columns):
                    worksheet.write(0, col_idx, col_name, header_fmt)
                    maior_valor = df[col_name].astype(str).str.len().max()
                    maior_valor = int(maior_valor) if pd.notna(maior_valor) else 12
                    largura = max(12, min(40, maior_valor + 2))
                    worksheet.set_column(col_idx, col_idx, largura)

        buffer.seek(0)
        nome_arquivo = f"Dados_RAC_{competencia.ano_mes.replace('-', '_')}.xlsx"
        return buffer.getvalue(), nome_arquivo
