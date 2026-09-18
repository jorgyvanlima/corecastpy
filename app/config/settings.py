import os

# ---------------------------------------------------------------------------
# Metas oficiais de SLA por prioridade (horas para finalizacao).
# Prioridades 3 e 4 sao parametrizaveis via variavel de ambiente para
# refletir acordos contratuais distintos por cliente/periodo.
# ---------------------------------------------------------------------------
SLA_META_HORAS_POR_PRIORIDADE = {
    1: 3.0,   # Critica
    2: 4.0,   # Alta
    3: float(os.getenv("SLA_META_P3_HORAS", "12")),   # Media (8h configuravel)
    4: float(os.getenv("SLA_META_P4_HORAS", "32")),   # Baixa (24h configuravel)
}

SLA_INICIO_META_MINUTOS = {
    1: 15,
    2: 15,
    3: 30,
    4: 240,
}

SLA_META_EFICIENCIA_PERCENTUAL = 95.0
SLA_META_AGING_PERCENTUAL = 100.0
SLA_META_REABERTURA_PERCENTUAL = 5.0

# Aging de 8 dias uteis/corridos, convertido para horas.
AGING_LIMITE_HORAS = 8 * 24  # 192 horas

# Conversao padrao quando a duracao em horas nao vem informada diretamente.
SEGUNDOS_POR_HORA_UTIL = 21600  # 6 horas uteis/dia consideradas na base ServiceNow

SECRET_KEY = os.getenv("SECRET_KEY", "corecast-dev-secret-change-me")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@corecast.local")
ADMIN_SENHA = os.getenv("ADMIN_SENHA", "admin123")
