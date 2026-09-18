"""Utilitarios de parsing/normalizacao usados pelo pipeline de importacao.

Centraliza as regras que corrigem os gargalos do sistema legado em PHP:
mapeamento de colunas por nome de cabecalho (nunca por posicao/letra fixa),
filtro de competencia por Iteration Path e extracao deterministica do
numero do chamado associado.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional

import pandas as pd

from app.config.settings import (
    AGING_LIMITE_HORAS,
    SEGUNDOS_POR_HORA_UTIL,
    SLA_META_HORAS_POR_PRIORIDADE,
)

NUMERO_CHAMADO_REGEX = re.compile(
    r"(INC\d+|RITM\d+|PRB\d+|CHG\d+|SCTASK\d+|TASK\d+)", re.IGNORECASE
)

MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "marco", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

MESES_ABREV_PT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr",
    5: "mai", 6: "jun", 7: "jul", 8: "ago",
    9: "set", 10: "out", 11: "nov", 12: "dez",
}


def normalize_text(valor) -> str:
    """Remove acentos, espacos nas bordas e converte para minusculas."""
    if valor is None:
        return ""
    texto = str(valor).strip()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return texto.lower()


def safe_str(valor) -> Optional[str]:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    texto = str(valor).strip()
    return texto if texto and texto.lower() != "nan" else None


def safe_float(valor) -> float:
    try:
        if valor is None or pd.isna(valor):
            return 0.0
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return 0.0


def safe_int(valor) -> int:
    try:
        if valor is None or pd.isna(valor):
            return 0
        return int(float(valor))
    except (TypeError, ValueError):
        return 0


def safe_datetime(valor):
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, datetime):
        return valor
    try:
        ts = pd.to_datetime(valor, errors="coerce", dayfirst=True)
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def find_column(colunas, aliases) -> Optional[str]:
    """Localiza a coluna real do DataFrame cujo nome corresponde a um alias.

    Nunca depende de posicao/indice fixo: compara nomes normalizados
    (sem acento, minusculo) por igualdade e, em seguida, por substring.
    """
    colunas_normalizadas = {coluna: normalize_text(coluna) for coluna in colunas}
    aliases_normalizados = [normalize_text(a) for a in aliases]

    for coluna, norm in colunas_normalizadas.items():
        if norm in aliases_normalizados:
            return coluna

    # Fallback por substring: so na direcao alias -> nome da coluna (uma
    # palavra-chave curta do alias encontrada dentro de um cabecalho mais
    # descritivo). A direcao inversa foi removida por causar falsos
    # positivos (ex.: coluna "Duration" casando com o alias "duration
    # (hours)" por "duration" ser substring do alias).
    #
    # Aliases com menos de 4 caracteres normalizados ficam de fora do
    # fallback (continuam valendo para o match exato acima). Um alias como
    # "nº" normaliza para "no" e, por substring, casaria com qualquer
    # cabecalho terminado nesse par de letras (ex.: "Codigo Interno" tem
    # "...terno", que contem "no") — um falso positivo real ja observado.
    TAMANHO_MINIMO_SUBSTRING = 4
    for coluna, norm in colunas_normalizadas.items():
        for alias in aliases_normalizados:
            if alias and len(alias) >= TAMANHO_MINIMO_SUBSTRING and alias in norm:
                return coluna
    return None


def map_columns(df: pd.DataFrame, mapa_aliases: dict) -> tuple[pd.DataFrame, dict]:
    """Retorna um DataFrame com colunas renomeadas para os nomes canonicos.

    Colunas nao encontradas ficam ausentes (o chamador deve tratar via
    ``.get`` com valor padrao) — nunca lemos por indice/letra fixa.

    Tambem retorna um dicionario de diagnostico ``{campo_canonico: coluna_real_ou_None}``
    para que o chamador possa avisar o usuario quando um cabecalho esperado
    nao foi localizado no arquivo enviado.
    """
    resultado = pd.DataFrame(index=df.index)
    mapeamento = {}
    for campo_canonico, aliases in mapa_aliases.items():
        coluna_real = find_column(df.columns, aliases)
        resultado[campo_canonico] = df[coluna_real] if coluna_real else None
        mapeamento[campo_canonico] = coluna_real
    return resultado, mapeamento


def extrair_chamado(titulo: Optional[str]) -> Optional[str]:
    if not titulo:
        return None
    match = NUMERO_CHAMADO_REGEX.search(str(titulo))
    return match.group(1).upper() if match else None


def normalizar_grupo_atribuicao(grupo: Optional[str]) -> Optional[str]:
    """Remove prefixos crus do ServiceNow/Azure DevOps do grupo de atribuicao.

    Ex.: "BR_CTR_L3_CAST_PowerPlatform" -> "PowerPlatform"
         "Global_CTR_L3_CAST_ServiceNow" -> "ServiceNow"
    """
    if not grupo:
        return grupo
    grupo = grupo.strip()

    sem_prefixo_cast = re.sub(r"^.*?_CAST_", "", grupo)
    if sem_prefixo_cast and sem_prefixo_cast != grupo:
        return sem_prefixo_cast.strip()

    sem_prefixo_ctr = re.sub(r"^[A-Za-z]+_CTR_L\d+_", "", grupo)
    return sem_prefixo_ctr.strip()


def parse_prioridade_num(prioridade: Optional[str]) -> int:
    if not prioridade:
        return 3
    match = re.search(r"([1-4])", str(prioridade))
    return int(match.group(1)) if match else 3


def calcular_duracao_horas(
    duracao_segundos: int = 0,
    duracao_negocios_segundos: int = 0,
    duracao_horas_informada: float = 0.0,
) -> float:
    """Calcula duracao_horas priorizando o valor ja informado na base.

    Quando ausente, deriva de duracao de negocios (regra oficial:
    duracao_horas = duracao_negocios_segundos / 21600) e, na falta desta,
    da duracao corrida em segundos.
    """
    if duracao_horas_informada and duracao_horas_informada > 0:
        return round(duracao_horas_informada, 2)
    if duracao_negocios_segundos and duracao_negocios_segundos > 0:
        return round(duracao_negocios_segundos / SEGUNDOS_POR_HORA_UTIL, 2)
    if duracao_segundos and duracao_segundos > 0:
        return round(duracao_segundos / 3600, 2)
    return 0.0


def calcular_meta_sla(prioridade: Optional[str]) -> float:
    prioridade_num = parse_prioridade_num(prioridade)
    return SLA_META_HORAS_POR_PRIORIDADE.get(prioridade_num, 12.0)


def calcular_status_sla(duracao_horas: float, meta_sla_horas: float) -> str:
    return "No Prazo" if duracao_horas <= meta_sla_horas else "Atraso"


def calcular_aging(duracao_horas: float) -> bool:
    return duracao_horas <= AGING_LIMITE_HORAS


def iteration_path_pertence_competencia(iteration_path: Optional[str], ano: int, mes: int) -> bool:
    """Filtro de competencia: mantem apenas linhas cujo Iteration Path
    corresponde ao mes/ano da competencia selecionada, evitando a inflacao
    de horas causada por itens de meses anteriores presentes no export.
    """
    if not iteration_path:
        return False

    texto = normalize_text(iteration_path)
    ano_str = str(ano)
    ano2 = ano_str[-2:]
    mes_full = MESES_PT[mes]
    mes_abrev = MESES_ABREV_PT[mes]
    mes_num = f"{mes:02d}"

    if ano_str in texto and (mes_full in texto or mes_abrev in texto):
        return True

    padroes_numericos = [
        f"{ano_str}-{mes_num}", f"{ano_str}/{mes_num}", f"{ano_str}.{mes_num}", f"{ano_str}_{mes_num}",
        f"{mes_num}-{ano_str}", f"{mes_num}/{ano_str}", f"{mes_num}.{ano_str}", f"{mes_num}_{ano_str}",
    ]
    if any(p in texto for p in padroes_numericos):
        return True

    combos_ano_2digitos = [
        f"{mes_abrev}-{ano2}", f"{mes_abrev}.{ano2}", f"{mes_abrev}/{ano2}",
        f"{mes_abrev}{ano2}", f"{mes_abrev}.-{ano2}", f"{mes_abrev}-.{ano2}",
    ]
    return any(c in texto for c in combos_ano_2digitos)
