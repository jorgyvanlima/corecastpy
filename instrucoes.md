Com base na especificação técnica e no diagnóstico de erros do sistema anterior presentes nos seus documentos, elaborei a arquitetura e o escopo completo para o **CoreCast**, um portal web moderno em **Python, PostgreSQL e Docker**.

Esta solução corrige os gargalos do PHP, como a volatilidade de leitura de colunas por letra fixa, erros de cruzamento não-determinístico de horas, cálculo incorreto de metas de SLA e inflação de horas por falta de filtro de competência no *Iteration Path* do Azure DevOps.

---

### 1. Visão Geral da Arquitetura do CoreCast

* **Stack Principal:** Python 3.11+ (FastAPI + SQLAlchemy + Pandas + OpenPyXL), PostgreSQL 15, Docker & Docker Compose.
* **Interface Web:** Jinja2 Templates + Bootstrap 5 / TailwindCSS + Chart.js para dashboards interativos de alta performance.
* **Garantia de Precisão Matemática:**
  1. **Mapeamento por Nome de Cabeçalho (*Header Index*):** Leitura de colunas por nome do rótulo e não por posição fixa.
  2. **Filtro de Competência de Horas:** Mantém apenas os *work items* cujo *Iteration Path* corresponde ao mês da competência (ex.: "Agosto 2026").
  3. **Cruzamento Determinístico de Horas:** Extração exata do número do chamado via Expressão Regular (`INC\d+|RITM\d+|PRB\d+`).
  4. **Metas de SLA Parametrizáveis:** Cálculo dinâmico de horas úteis e cumprimento do SLA.
  5. **Controle de Aging (8 dias):** Apuração separada para chamados concluídos em até 192 horas úteis/corridas.

---

### 2. Estrutura do Banco de Dados PostgreSQL (`init.sql`)

```sql
-- 1. Usuários e Autenticação
CREATE TABLE usuarios (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    senha_hash VARCHAR(255) NOT NULL,
    perfil VARCHAR(20) DEFAULT 'analista', -- 'admin' | 'analista'
    ativo BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Competências (Anual / Mensal)
CREATE TABLE competencias (
    id SERIAL PRIMARY KEY,
    ano_mes VARCHAR(7) UNIQUE NOT NULL, -- Ex: '2026-08'
    rotulo VARCHAR(50) NOT NULL,       -- Ex: 'Agosto/2026'
    status VARCHAR(20) DEFAULT 'Aberta', -- 'Aberta' | 'Fechada'
    total_horas NUMERIC(10,2) DEFAULT 0,
    total_incidentes INT DEFAULT 0,
    total_requisicoes INT DEFAULT 0,
    total_melhorias INT DEFAULT 0,
    sla_cumprimento NUMERIC(5,2) DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Horas Tereos (DevOps)
CREATE TABLE horas_tereos (
    id SERIAL PRIMARY KEY,
    competencia_id INT NOT NULL REFERENCES competencias(id) ON DELETE CASCADE,
    title TEXT,
    work_item_id VARCHAR(50),
    work_item_type VARCHAR(50),
    assigned_to VARCHAR(150),
    state VARCHAR(50),
    grupo_atribuicao VARCHAR(100),
    horas NUMERIC(10,2) DEFAULT 0,
    iteration_path VARCHAR(100),
    chamado_associado VARCHAR(50) -- Extraído via Regex (INC... / RITM...)
);

-- 4. Incidentes (ServiceNow - INC)
CREATE TABLE incidentes (
    id SERIAL PRIMARY KEY,
    competencia_id INT NOT NULL REFERENCES competencias(id) ON DELETE CASCADE,
    numero VARCHAR(50) NOT NULL,
    criado_em TIMESTAMP,
    estado VARCHAR(50) DEFAULT 'Encerrado',
    atribuicao_a VARCHAR(150),
    grupo_atribuicao VARCHAR(100),
    business_application VARCHAR(150),
    data_ultimo_comentario TIMESTAMP,
    prioridade VARCHAR(50), -- Ex: '3 - Média'
    duracao_segundos BIGINT DEFAULT 0,
    duracao_negocios_segundos BIGINT DEFAULT 0,
    duracao_horas NUMERIC(10,2) DEFAULT 0,
    meta_sla_horas NUMERIC(10,2) DEFAULT 12,
    status_sla VARCHAR(20) DEFAULT 'No Prazo', -- 'No Prazo' | 'Atraso'
    dentro_aging_8dias BOOLEAN DEFAULT TRUE,
    contagem_reaberturas INT DEFAULT 0,
    horas_consumidas NUMERIC(10,2) DEFAULT 0,
    descricao_resumida TEXT
);

-- 5. Requisições (ServiceNow - RITM)
CREATE TABLE requisicoes (
    id SERIAL PRIMARY KEY,
    competencia_id INT NOT NULL REFERENCES competencias(id) ON DELETE CASCADE,
    numero VARCHAR(50) NOT NULL,
    classificacao_demanda VARCHAR(100),
    complexidade_demanda VARCHAR(50),
    criacao_em TIMESTAMP,
    estado VARCHAR(50),
    grupo_atribuicao VARCHAR(100),
    atribuicao_a VARCHAR(150),
    business_application VARCHAR(150),
    horas_consumidas NUMERIC(10,2) DEFAULT 0
);

-- 6. Posição de Melhorias & Baseline
CREATE TABLE melhorias (
    id SERIAL PRIMARY KEY,
    competencia_id INT NOT NULL REFERENCES competencias(id) ON DELETE CASCADE,
    ritm_numero VARCHAR(50),
    aplicacao VARCHAR(100),
    descricao TEXT,
    horas_estimadas NUMERIC(10,2) DEFAULT 0,
    horas_consumidas NUMERIC(10,2) DEFAULT 0,
    status VARCHAR(50) DEFAULT 'Em Andamento', -- 'Em Andamento' | 'Em Homologação' | 'Finalizada'
    solicitante VARCHAR(150)
);

-- Índices de Alta Performance
CREATE INDEX idx_horas_comp ON horas_tereos(competencia_id);
CREATE INDEX idx_inc_comp ON incidentes(competencia_id);
CREATE INDEX idx_inc_num ON incidentes(numero);
CREATE INDEX idx_req_comp ON requisicoes(competencia_id);
CREATE INDEX idx_req_num ON requisicoes(numero);
```

---

### 3. Script Python de Gerador de Estrutura de Projeto (`setup_corecast.py`)

Execute este script no terminal dentro da pasta onde deseja criar o projeto no VS Code:

```python
import os

files = {
    "docker-compose.yml": """version: '3.8'
services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://corecast_user:corecast_pass@db:5432/corecast_db
    depends_on:
      - db
    volumes:
      - .:/app

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: corecast_db
      POSTGRES_USER: corecast_user
      POSTGRES_PASSWORD: corecast_pass
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./database/init.sql:/docker-entrypoint-initdb.d/init.sql

volumes:
  pgdata:
""",
    "Dockerfile": """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
""",
    "requirements.txt": """fastapi>=0.100.0
uvicorn>=0.22.0
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.6
pandas>=2.0.0
openpyxl>=3.1.2
jinja2>=3.1.2
python-multipart>=0.0.6
passlib[bcrypt]>=1.7.4
""",
    "app/__init__.py": "",
    "app/main.py": """from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import importador, dashboard, anual, competencias

app = FastAPI(title="CoreCast - Gestão de Atendimentos & SLA")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(importador.router)
app.include_router(dashboard.router)
app.include_router(anual.router)
app.include_router(competencias.router)

@app.get("/")
def root():
    return {"message": "Portal CoreCast em execução com sucesso!"}
""",
    "app/config/database.py": """import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://corecast_user:corecast_pass@localhost:5432/corecast_db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
""",
    "app/services/import_service.py": """import re
import pandas as pd
from sqlalchemy.orm import Session

NUMERO_CHAMADO_REGEX = r'(INC\d+|RITM\d+|PRB\d+|CHG\d+|SCTASK\d+|TASK\d+)'

class FileImportService:
    @staticmethod
    def process_import(db: Session, competencia_id: int, horas_file, inc_file, req_file):
        # 1. Limpeza Idempotente da Competência
        db.execute(f"DELETE FROM horas_tereos WHERE competencia_id = {competencia_id}")
        db.execute(f"DELETE FROM incidentes WHERE competencia_id = {competencia_id}")
        db.execute(f"DELETE FROM requisicoes WHERE competencia_id = {competencia_id}")
        db.commit()
        
        # 2. Leitura por Nome de Cabeçalho (Header Matching) e Processamento
        # [A lógica detalhada de Parsing e SLA é injetada via prompt no agente]
        return {"status": "sucesso", "mensagem": "Importação concluída com sucesso."}
""",
    "app/routers/__init__.py": "",
    "app/routers/importador.py": """from fastapi import APIRouter
router = APIRouter(prefix="/importar", tags=["Importação"])
""",
    "app/routers/dashboard.py": """from fastapi import APIRouter
router = APIRouter(prefix="/dashboard", tags=["Dashboard Mensal"])
""",
    "app/routers/anual.py": """from fastapi import APIRouter
router = APIRouter(prefix="/anual", tags=["Parâmetro Anual"])
""",
    "app/routers/competencias.py": """from fastapi import APIRouter
router = APIRouter(prefix="/competencias", tags=["Gestão de Bases"])
""",
    "app/templates/base.html": "<!DOCTYPE html><html><head><title>CoreCast</title></head><body><h1>CoreCast Portal</h1></body></html>",
    "database/init.sql": "-- Cole aqui o SQL da Seção 2"
}

for path, content in files.items():
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

print("Estrutura do projeto CoreCast criada com sucesso!")
```

---

### 4. Prompt Mestre para Copiar e Colar no VS Code (Cursor / Claude Code / Copilot)

> Copie todo o bloco abaixo e cole no seu agente do VS Code após ter criado os arquivos base:

```text
Você é o Arquiteto de Software Principal responsável por desenvolver o sistema web profissional "CoreCast" em Python 3.11, FastAPI, PostgreSQL e Docker.

OBJETIVO DO SISTEMA:
O CoreCast é um portal executivo para gestão de atendimentos AMS, controle de esforço e apuração rigorosa de SLA para o contrato Cast Group / Tereos. Ele substitui um sistema legado em PHP que apresentava erros matemáticos sérios de SLA, duplicidade não-determinística de horas e falhas de leitura por colunas fixas.

REGRAS DE NEGÓCIO E REGRA MATEMÁTICA RIGOROSA:

1. PIPELINE DE IMPORTAÇÃO (PÁGINA 1 - /importar):
   - Arquivos brutos recebidos:
     a) Horas Tereos: horas_tereos.csv ou .xlsx (Azure DevOps).
     b) Incidentes: incident_XX.xlsx (ServiceNow).
     c) Requisições: sc_req_item_XX.xlsx (ServiceNow).
     d) Consolidado opcional: Dados_RAC_XX-XXXX.xlsx (possui 3 abas correspondentes aos arquivos brutos e tem precedência se enviado).
   - ESTRATÉGIA IDEMPOTENTE: Antes de importar os dados de uma competência (ex.: 2026-08), EXCLUA todos os registros prévios dessa competencia_id (DELETE FROM ... WHERE competencia_id = :id).
   - LEITURA POR NOME DE CABEÇALHO (Header Indexing): NUNCA leia colunas por índice ou letra fixa. Mapeie dinamicamente pelo nome da coluna no cabeçalho (ex.: "Effort", "Title", "Iteration Path", "Número", "Prioridade", "Duração").
   - FILTRO DE COMPETÊNCIA EM HORAS TEREOS: O export do Azure DevOps traz itens de meses anteriores. MANTENHA APENAS as linhas cujo 'Iteration Path' corresponda ao mês/ano da competência selecionada (ex.: "Agosto 2026" / "ago.-26").
   - CRUZAMENTO DETERMINÍSTICO DE HORAS (Cross-Referencing): Extraia o número do chamado usando a regex `(INC\d+|RITM\d+|PRB\d+|CHG\d+|SCTASK\d+|TASK\d+)` a partir do campo 'Title' das Horas Tereos. Faça o match exato por número do chamado com incidentes e requisições da mesma competência. Caso haja múltiplas linhas no mesmo mês para o mesmo chamado, ordene de forma determinística mantendo a soma das horas do mês.
   - NORMALIZAÇÃO DE GRUPO DE ATRIBUIÇÃO: Remova prefixos crus do ServiceNow (ex.: "BR_CTR_L3_CAST_PowerPlatform" -> "PowerPlatform", "Global_CTR_L3_CAST_ServiceNow" -> "ServiceNow").

2. REGRAS DE SLA E AGING (PÁGINA 2 - /dashboard):
   - Metas Oficiais de SLA por Prioridade (Finalização):
     * 1 - Crítica: 3 horas (Início: 15 min)
     * 2 - Alta: 4 horas (Início: 15 min)
     * 3 - Média: 12 horas (ou 8h configurável) (Início: 30 min)
     * 4 - Baixa: 32 horas (ou 24h configurável) (Início: 4 horas)
   - Status SLA: Se (duracao_horas <= meta_sla_horas) ENTÃO 'No Prazo', SENÃO 'Atraso'.
   - Conversão de Duração de Negócios: Se a duração em horas não vier informada, calcule: duracao_horas = duracao_negocios_segundos / 21600 (arredondado em 2 casas).
   - Apuração de Aging (< 8 dias): O chamado está dentro do aging quando duracao_horas <= 192 horas (8 dias x 24h).
   - Fórmulas dos Cards Executivos:
     * Eficiência de SLA (%) = (Incidentes 'No Prazo' / Total de Incidentes) * 100 [Meta >= 95%]
     * Aging 8 Dias (%) = (Incidentes com dentro_aging_8dias = True / Total de Incidentes) * 100 [Meta = 100%]
     * Taxa de Reabertura (%) = (Soma das reaberturas / Total de Incidentes) * 100 [Meta <= 5%]
     * Total de Horas = Soma do esforço total de Horas Tereos apontadas no mês.

3. PARÂMETRO ANUAL E VISÃO TRIMESTRAL (PÁGINA 3 - /anual):
   - Apresente tabelas e gráficos da evolução mensal e trimestral dos indicadores.
   - Posição do Baseline Trimestral de Melhorias:
     * Saldo Anterior Trimestral (ex.: 899.77h)
     * Horas Estimadas em Melhorias no Período
     * Saldo Atualizado = MAX(0, Saldo Anterior - Horas Estimadas)
   - Tabela de dados brutos com filtros dinâmicos e controle total de inclusão/exclusão de competências mensais (CRUD completo de bases mensais).

4. EXPORTAÇÃO EXCEL (/exportar/dados-rac):
   - Crie uma rota para gerar e baixar a planilha oficial "Dados_RAC_XX-XXXX.xlsx" com abas formatadas contendo os dados processados e consolidados.

LAYOUT E INTERFACE:
Crie uma interface moderna usando Jinja2, Bootstrap 5 e Chart.js, mantendo uma paleta corporativa elegante (Azul Escuro / Roxo / Verde / Vermelho).

Por favor, implemente o código completo de todos os arquivos do projeto (Backend FastAPI, Models SQLAlchemy, Serviços de Importação com Pandas/Regex, Visualizações com Chart.js e Rotas HTML).
```

---

### O que você deve fazer agora:
1. Salve e execute o script `setup_corecast.py` no terminal da sua pasta de trabalho no VS Code.
2. Suba o ambiente containerizado com o comando:
   ```bash
   docker compose up -d --build
   ```
3. Abra o seu assistente de IA no VS Code (Cursor / Claude Code / Copilot) e cole o **Prompt Mestre** acima para gerar todos os arquivos desenvolvidos com matemática de precisão!

Se quiser ajustar algum cálculo específico do baseline trimestral ou das metas contratuais, é só me avisar!