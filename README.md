# CoreCast

Portal executivo de gestão de atendimentos AMS, controle de esforço e apuração de SLA para o contrato **Cast Group / Tereos**. Substitui um sistema legado em PHP que apresentava erros matemáticos de SLA, duplicidade não determinística de horas e falhas de leitura por colunas fixas.

Stack: **Python 3.11 · FastAPI · SQLAlchemy · PostgreSQL 15 · Pandas/OpenPyXL · Jinja2 + AdminLTE 4 (Bootstrap 5) + ApexCharts · Docker Compose**.

---

## Índice

- [Visão geral](#visão-geral)
- [Por que este projeto existe](#por-que-este-projeto-existe)
- [Arquitetura](#arquitetura)
- [Regras de negócio](#regras-de-negócio)
- [Modelo de dados](#modelo-de-dados)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Como executar](#como-executar)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Primeiro acesso](#primeiro-acesso)
- [Guia de uso](#guia-de-uso)
- [Formato dos arquivos de importação](#formato-dos-arquivos-de-importação)
- [Referência de rotas](#referência-de-rotas)
- [Exportação de dados](#exportação-de-dados)
- [Desenvolvimento sem Docker](#desenvolvimento-sem-docker)
- [Solução de problemas](#solução-de-problemas)
- [Segurança](#segurança)
- [Limitações conhecidas / roadmap](#limitações-conhecidas--roadmap)

---

## Visão geral

O CoreCast processa três origens de dados mensais — **horas apontadas no Azure DevOps**, **incidentes** e **requisições do ServiceNow** — e produz:

- Apuração determinística de SLA e *aging* por incidente;
- Cruzamento de horas apontadas com os chamados que as originaram;
- Dashboards executivos com metas contratuais;
- Visão anual/trimestral com baseline de horas de melhorias;
- Exportação da planilha oficial consolidada `Dados_RAC`.

## Por que este projeto existe

O sistema legado em PHP lia colunas por letra fixa (`B2`, `H15`...), o que quebrava toda vez que um export do ServiceNow ou do Azure DevOps mudava a ordem das colunas. Além disso:

| Problema no legado | Causa raiz | Correção no CoreCast |
|---|---|---|
| Horas de meses errados entram no fechamento mensal | Sem filtro de competência no export do Azure DevOps (`Iteration Path`) | Filtro determinístico de competência antes de persistir qualquer linha de horas — [`iteration_path_pertence_competencia`](app/services/parsing_utils.py) |
| Cruzamento de horas com chamados duplica ou perde valores | Parsing de texto livre não determinístico | Extração via regex fixa `(INC\d+\|RITM\d+\|PRB\d+\|CHG\d+\|SCTASK\d+\|TASK\d+)` sobre o campo `Title`, com soma agregada por chamado — [`extrair_chamado`](app/services/parsing_utils.py) |
| Meta de SLA calculada errada | Meta fixa única, sem levar em conta prioridade | Meta por prioridade (1 a 4), parametrizável via variável de ambiente para P3/P4 |
| Leitura de coluna por posição quebra com qualquer mudança de layout | Índice fixo (`row[3]`, coluna `D`) | Mapeamento por **nome de cabeçalho**, tolerante a acentuação/caixa — [`find_column` / `map_columns`](app/services/parsing_utils.py) |
| Reimportação de uma competência duplica registros | Sem limpeza prévia | Estratégia idempotente: `DELETE` de todos os registros da competência antes de cada importação — [`FileImportService.process_import`](app/services/import_service.py) |

## Arquitetura

```
Navegador ── Jinja2 + AdminLTE 4 (Bootstrap 5) + ApexCharts (SSR, sem SPA)
     │
     ▼
FastAPI (app/main.py)
 ├── SessionMiddleware (login por sessão de servidor, cookie assinado)
 ├── routers/
 │    ├── auth.py         → /login /logout
 │    ├── importador.py   → /importar
 │    ├── dashboard.py    → /dashboard
 │    ├── anual.py        → /anual (+ baseline + melhorias)
 │    ├── competencias.py → /competencias (CRUD)
 │    └── exportar.py     → /exportar/dados-rac
 ├── services/
 │    ├── parsing_utils.py   → normalização, regex, filtro de competência
 │    ├── import_service.py  → pipeline de importação (ETL)
 │    └── export_service.py  → geração do Excel Dados_RAC
 └── models/models.py → ORM SQLAlchemy (1:1 com database/init.sql)
     │
     ▼
PostgreSQL 15 (container `db`, schema aplicado via docker-entrypoint-initdb.d)
```

Cada container:

- **`web`** — imagem própria ([`Dockerfile`](Dockerfile)), `uvicorn --reload`, código montado como volume para hot-reload em desenvolvimento.
- **`db`** — `postgres:15-alpine`, aplica [`database/init.sql`](database/init.sql) automaticamente na primeira subida (volume novo) e expõe *healthcheck* via `pg_isready`; o serviço `web` só sobe depois que o banco está saudável (`depends_on.condition: service_healthy`).

## Regras de negócio

### 1. Pipeline de importação (`/importar`)

Implementado em [`app/services/import_service.py`](app/services/import_service.py), chamado por `FileImportService.process_import`:

1. **Resolução da fonte de dados** — se um arquivo `Dados_RAC_XX-XXXX.xlsx` (consolidado) for enviado, ele tem precedência total: suas 3 abas são identificadas por palavras-chave no nome (`hora`/`tereos`/`devops`, `inc`, `req`/`ritm`) com *fallback* posicional (1ª aba = horas, 2ª = incidentes, 3ª = requisições) caso a nomenclatura não seja reconhecida.
2. **Limpeza idempotente** — antes de gravar qualquer linha nova, todos os registros de `horas_tereos`, `incidentes` e `requisicoes` da `competencia_id` são apagados (`DELETE ... WHERE competencia_id = :id`). Reimportar a mesma competência nunca duplica dados.
3. **Leitura por nome de cabeçalho** — cada arquivo é mapeado por um dicionário de sinônimos tolerante a acento/caixa (`find_column`/`map_columns`). Nunca há leitura por índice de coluna. Ver a tabela completa em [Formato dos arquivos de importação](#formato-dos-arquivos-de-importação).
4. **Filtro de competência em Horas Tereos** — cada linha só é persistida se o `Iteration Path` corresponder ao mês/ano da competência selecionada. O comparador aceita variações como `"Agosto 2026"`, `"ago.-26"`, `"2026-08"`, `"08/2026"` (ver `iteration_path_pertence_competencia`).
5. **Cruzamento determinístico de horas** — o número do chamado é extraído do campo `Title` via regex; as horas de todas as linhas do mesmo chamado dentro da competência são somadas em um dicionário `{numero_chamado: total_horas}` e aplicadas ao campo `horas_consumidas` do incidente/requisição correspondente.
6. **Normalização de grupo de atribuição** — remove prefixos crus do ServiceNow/Azure DevOps: `"BR_CTR_L3_CAST_PowerPlatform"` → `"PowerPlatform"`, `"Global_CTR_L3_CAST_ServiceNow"` → `"ServiceNow"` (regra: tudo até e incluindo o primeiro `_CAST_` é removido; se não houver esse marcador, remove o padrão `LETRAS_CTR_L\d_`).
7. **Totais da competência** são recalculados ao final da importação (`total_horas`, `total_incidentes`, `total_requisicoes`, `sla_cumprimento`) e persistidos na tabela `competencias`.

### 2. SLA e Aging (`/dashboard`)

Metas oficiais de SLA por prioridade (finalização), definidas em [`app/config/settings.py`](app/config/settings.py):

| Prioridade | Meta de finalização | Meta de início | Configurável via env |
|---|---|---|---|
| 1 — Crítica | 3h | 15 min | — |
| 2 — Alta | 4h | 15 min | — |
| 3 — Média | 12h (padrão) | 30 min | `SLA_META_P3_HORAS` |
| 4 — Baixa | 32h (padrão) | 4h | `SLA_META_P4_HORAS` |

> A meta de *início* de atendimento é apenas referenciada em `settings.py` (`SLA_INICIO_META_MINUTOS`) — não é calculada, pois os exports padrão do ServiceNow descritos nas instruções do projeto não trazem um campo de "primeira resposta". Ver [Limitações conhecidas](#limitações-conhecidas--roadmap).

Fórmulas aplicadas linha a linha durante a importação (`app/services/parsing_utils.py`):

```
duracao_horas   = duracao_horas_informada                          , se > 0
                = duracao_negocios_segundos / 21600 (arred. 2 casas), senão
                = duracao_segundos / 3600 (arred. 2 casas)          , senão
                = 0

status_sla      = "No Prazo" se duracao_horas <= meta_sla_horas, senão "Atraso"

dentro_aging_8dias = duracao_horas <= 192   (8 dias × 24h)
```

Fórmulas dos cards executivos do dashboard (`app/routers/dashboard.py`):

```
Eficiência de SLA (%)   = (incidentes "No Prazo" / total de incidentes) × 100     [Meta ≥ 95%]
Aging 8 Dias (%)        = (incidentes dentro_aging_8dias / total de incidentes) × 100  [Meta = 100%]
Taxa de Reabertura (%)  = (Σ contagem_reaberturas / total de incidentes) × 100    [Meta ≤ 5%]
Total de Horas          = Σ horas_tereos.horas da competência
```

### 3. Parâmetro anual e baseline trimestral (`/anual`)

- Agrega as competências do ano selecionado em 4 trimestres (Q1: jan–mar, Q2: abr–jun, Q3: jul–set, Q4: out–dez), recalculando eficiência de SLA, aging e reabertura por trimestre.
- **Baseline de melhorias** (tabela `baseline_trimestral`): o saldo anterior é editável por trimestre; o saldo atualizado é recalculado a cada submissão:

  ```
  saldo_atualizado = MAX(0, saldo_anterior − horas_estimadas_no_periodo)
  ```

  onde `horas_estimadas_no_periodo` é a soma de `melhorias.horas_estimadas` de todas as competências pertencentes ao trimestre selecionado.
- A tabela `melhorias` não possui um arquivo de importação dedicado nas instruções originais do projeto — por isso o CRUD é feito diretamente na página `/anual` (registrar RITM, aplicação, horas estimadas, status, solicitante).
- CRUD completo de competências mensais (criar, reabrir/fechar, excluir) em `/competencias`. **Excluir uma competência remove em cascata** todas as horas, incidentes, requisições e melhorias vinculadas (`ON DELETE CASCADE` no schema).

## Modelo de dados

Schema completo em [`database/init.sql`](database/init.sql), espelhado 1:1 pelo ORM em [`app/models/models.py`](app/models/models.py):

| Tabela | Papel |
|---|---|
| `usuarios` | Autenticação (bcrypt) e perfil (`admin` / `analista`) |
| `competencias` | Uma linha por mês (`ano_mes` único, ex. `2026-08`); guarda os totais consolidados e o status `Aberta`/`Fechada` |
| `horas_tereos` | Linhas de esforço do Azure DevOps já filtradas pela competência, com `chamado_associado` extraído por regex |
| `incidentes` | Chamados INC do ServiceNow com SLA, aging e reaberturas já calculados |
| `requisicoes` | Chamados RITM do ServiceNow |
| `melhorias` | Posições de melhoria (RITM, horas estimadas/consumidas, status) usadas no baseline trimestral |
| `baseline_trimestral` | Saldo anterior de horas de melhorias por trimestre (`YYYY-Qn`) |

Índices dedicados em `competencia_id` e `numero`/`chamado_associado` para consultas e cruzamentos de alta performance (ver final de `init.sql`).

## Estrutura do repositório

```
corecastpy/
├── database/
│   └── init.sql                 # schema PostgreSQL, aplicado automaticamente pelo container db
├── app/
│   ├── main.py                  # bootstrap FastAPI, sessão, seed do admin, exception handler
│   ├── config/
│   │   ├── database.py          # engine/SessionLocal/Base (SQLAlchemy)
│   │   ├── security.py          # hash/verify de senha, dependências de login/admin
│   │   └── settings.py          # metas de SLA/aging, chaves e credenciais via env
│   ├── models/models.py         # ORM (Usuario, Competencia, HorasTereos, Incidente, Requisicao, Melhoria, BaselineTrimestral)
│   ├── services/
│   │   ├── parsing_utils.py     # normalização, regex, mapeamento de cabeçalho, filtro de competência
│   │   ├── import_service.py    # pipeline de importação (ETL) — FileImportService
│   │   └── export_service.py    # geração do Excel Dados_RAC — ExportService
│   ├── routers/                 # auth, importador, dashboard, anual, competencias, exportar
│   ├── templates/                # Jinja2 (base, login, importar, dashboard, anual, competencias)
│   ├── static/css/custom.css     # paleta corporativa sobreposta ao tema padrao do AdminLTE 4
│   └── templates_engine.py      # instância compartilhada de Jinja2Templates
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── instrucoes.md                # especificação original do projeto
```

## Como executar

Pré-requisitos: **Docker** e **Docker Compose** (v2).

```bash
git clone https://github.com/jorgyvanlima/corecastpy.git
cd corecastpy
docker compose up -d --build
```

O compose sobe dois serviços:

- `web` → aplicação FastAPI, porta **8092** do host (`8092:8000` no container)
- `db` → PostgreSQL, porta **5434** do host (`5434:5432` no container)

Acesse: **http://localhost:8092**

> **Portas remapeadas.** Os valores padrão de FastAPI/Postgres são `8000`/`5432`; neste repositório eles foram remapeados para `8092`/`5434` para evitar conflito com outros containers já em uso no ambiente de desenvolvimento original. Se sua máquina tiver as portas `8000`/`5432` livres, sinta-se à vontade para voltar aos valores padrão editando [`docker-compose.yml`](docker-compose.yml) — a comunicação interna entre os containers (`DATABASE_URL=postgresql://...@db:5432/...`) não é afetada por essa mudança, pois usa a rede interna do Compose.

Para acompanhar os logs:

```bash
docker compose logs -f web
```

Para parar:

```bash
docker compose down          # mantém os dados (volume pgdata)
docker compose down -v       # remove também o volume do banco
```

## Variáveis de ambiente

Definidas em [`docker-compose.yml`](docker-compose.yml) com valores padrão, sobrescrevíveis criando um arquivo `.env` na raiz (veja [`.env.example`](.env.example)):

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` | `postgresql://corecast_user:corecast_pass@db:5432/corecast_db` | String de conexão usada pelo SQLAlchemy |
| `SECRET_KEY` | `corecast-dev-secret-change-me` | Chave de assinatura do cookie de sessão (`SessionMiddleware`) — **troque em produção** |
| `SLA_META_P3_HORAS` | `12` | Meta de SLA (horas) para prioridade 3 — Média |
| `SLA_META_P4_HORAS` | `32` | Meta de SLA (horas) para prioridade 4 — Baixa |
| `ADMIN_EMAIL` | `admin@corecast.local` | E-mail do usuário administrador criado automaticamente no primeiro start |
| `ADMIN_SENHA` | `admin123` | Senha do usuário administrador criado automaticamente — **troque em produção** |

O usuário admin só é criado se a tabela `usuarios` estiver vazia (checagem em `iniciar_aplicacao`, [`app/main.py`](app/main.py)). Alterar `ADMIN_EMAIL`/`ADMIN_SENHA` depois que o admin já existe não tem efeito — troque a senha pelo próprio sistema ou diretamente no banco.

## Primeiro acesso

1. Acesse `http://localhost:8092` → redireciona para `/login`.
2. Entre com as credenciais padrão (ou as definidas via `ADMIN_EMAIL`/`ADMIN_SENHA`):
   - **E-mail:** `admin@corecast.local`
   - **Senha:** `admin123`
3. Você será redirecionado para `/dashboard`.

## Guia de uso

### `/importar`
Selecione uma competência existente **ou** crie uma nova informando mês/ano. Envie os três arquivos brutos (Horas Tereos, Incidentes, Requisições) **ou** um único consolidado `Dados_RAC` (que tem precedência sobre os brutos se ambos forem enviados). Ao processar, a importação anterior daquela competência é completamente substituída.

### `/dashboard`
Selecione a competência no topo da página. Mostra os 4 cards executivos com badges verde/vermelho conforme a meta contratual, gráficos (SLA por prioridade, distribuição No Prazo × Atraso, horas por grupo de atribuição) e a tabela dos 10 incidentes mais atrasados. Link direto para exportar o `Dados_RAC` da competência selecionada.

### `/anual`
Selecione o ano. Mostra os 4 cards trimestrais, o formulário de baseline de melhorias do trimestre em foco (clique em "Ver baseline" em qualquer card trimestral para trocar o foco), o CRUD de melhorias do período, o gráfico de evolução mensal (eficiência de SLA, aging, total de horas) e a tabela detalhada mês a mês.

### `/competencias`
CRUD completo das bases mensais: criar nova competência, fechar/reabrir, ou excluir (remove em cascata todos os dados vinculados — a interface pede confirmação antes).

## Formato dos arquivos de importação

O mapeamento é por **nome de cabeçalho** (case/acento-insensível), não por posição. As colunas abaixo são reconhecidas automaticamente; qualquer nome de coluna não listado é ignorado (permanece `None`/vazio no registro).

**Horas Tereos** (Azure DevOps, `.csv` ou `.xlsx`) — mapa em `HORAS_COLS`:

| Campo interno | Cabeçalhos aceitos |
|---|---|
| `title` | `Title`, `Título`, `Titulo` |
| `work_item_id` | `ID`, `Work Item ID`, `Item ID`, `WorkItem ID` |
| `work_item_type` | `Work Item Type`, `Tipo`, `Type` |
| `assigned_to` | `Assigned To`, `Atribuído a`, `Responsável` |
| `state` | `State`, `Estado` |
| `grupo_atribuicao` | `Area Path`, `Team`, `Grupo de Atribuição`, `Assignment Group` |
| `horas` | `Effort`, `Completed Work`, `Horas`, `Esforço` |
| `iteration_path` | `Iteration Path`, `Iteration`, `Sprint` |

**Incidentes** (`incident_XX.xlsx`) — mapa em `INC_COLS`:

| Campo interno | Cabeçalhos aceitos |
|---|---|
| `numero` | `Number`, `Número` |
| `criado_em` | `Opened`, `Created`, `Criado em`, `Data de Abertura` |
| `estado` | `State`, `Estado` |
| `atribuicao_a` | `Assigned to`, `Atribuído a` |
| `grupo_atribuicao` | `Assignment group`, `Grupo de Atribuição` |
| `business_application` | `Business application`, `Aplicação de Negócio` |
| `data_ultimo_comentario` | `Updated`, `Last Updated`, `Data do Último Comentário` |
| `prioridade` | `Priority`, `Prioridade` (ex.: `"3 - Média"`) |
| `duracao_segundos` | `Duration`, `Duração` |
| `duracao_negocios_segundos` | `Business duration`, `Duração de Negócios` |
| `duracao_horas` | `Duration (Hours)`, `Duração Horas` |
| `contagem_reaberturas` | `Reopen count`, `Reaberturas` |
| `descricao_resumida` | `Short description`, `Descrição Resumida` |

**Requisições** (`sc_req_item_XX.xlsx`) — mapa em `REQ_COLS`:

| Campo interno | Cabeçalhos aceitos |
|---|---|
| `numero` | `Number`, `Número` |
| `classificacao_demanda` | `Request classification`, `Classificação da Demanda` |
| `complexidade_demanda` | `Complexity`, `Complexidade` |
| `criacao_em` | `Opened`, `Created`, `Criado em` |
| `estado` | `State`, `Estado` |
| `grupo_atribuicao` | `Assignment group`, `Grupo de Atribuição` |
| `atribuicao_a` | `Assigned to`, `Atribuído a` |
| `business_application` | `Business application`, `Aplicação de Negócio` |
| `horas_consumidas` | `Horas Consumidas`, `Effort`, `Horas` (sobrescrito pelo cruzamento com Horas Tereos quando houver correspondência de chamado) |

**Consolidado `Dados_RAC_XX-XXXX.xlsx`**: arquivo único com 3 abas. As abas são identificadas por palavras-chave no nome (`hora`/`tereos`/`devops` → Horas; `inc` → Incidentes; `req`/`ritm` → Requisições); se os nomes não corresponderem, a 1ª, 2ª e 3ª abas são usadas nessa ordem.

## Referência de rotas

Todas as rotas abaixo (exceto `/login`) exigem sessão autenticada — sem sessão, o middleware redireciona (`303`) para `/login`.

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Redireciona para `/dashboard` |
| `GET`/`POST` | `/login` | Formulário e autenticação |
| `GET` | `/logout` | Encerra a sessão |
| `GET`/`POST` | `/importar` | Formulário e processamento da importação |
| `GET` | `/dashboard?competencia_id=` | Dashboard mensal |
| `GET` | `/anual?ano=&trimestre=` | Visão anual/trimestral |
| `POST` | `/anual/baseline` | Atualiza o saldo anterior do trimestre |
| `POST` | `/anual/melhorias` | Cria uma melhoria vinculada a uma competência do trimestre |
| `POST` | `/anual/melhorias/{id}/excluir` | Remove uma melhoria |
| `GET`/`POST` | `/competencias` | Lista e cria competências |
| `POST` | `/competencias/{id}/status` | Alterna Aberta ⇄ Fechada |
| `POST` | `/competencias/{id}/excluir` | Exclui a competência e todos os dados vinculados (cascade) |
| `GET` | `/exportar/dados-rac?competencia_id=` | Baixa o Excel consolidado da competência |

## Exportação de dados

`GET /exportar/dados-rac?competencia_id=<id>` gera em memória (via `xlsxwriter`, sem gravar em disco) o arquivo `Dados_RAC_<ano>_<mes>.xlsx` com 4 abas formatadas (cabeçalho em azul escuro/branco, colunas com largura ajustada ao conteúdo): **Horas Tereos**, **Incidentes**, **Requisições**, **Melhorias** — implementado em [`ExportService.gerar_dados_rac`](app/services/export_service.py).

## Desenvolvimento sem Docker

Requer Python 3.11+ e um PostgreSQL acessível localmente.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DATABASE_URL=postgresql://corecast_user:corecast_pass@localhost:5432/corecast_db
export SECRET_KEY=dev-secret

# aplica o schema manualmente (o container db faz isso sozinho via docker-entrypoint-initdb.d)
psql "$DATABASE_URL" -f database/init.sql

uvicorn app.main:app --reload --port 8000
```

O `create_all` do SQLAlchemy roda no `startup` da aplicação como rede de segurança (não recria tabelas já existentes), mas o schema oficial e as constraints/índices completos estão em `database/init.sql`.

## Solução de problemas

- **`Bind for 0.0.0.0:XXXX failed: port is already allocated`** — outra aplicação/container já usa a porta. Ajuste o mapeamento em `docker-compose.yml` (ex.: `"8093:8000"`) e suba novamente com `docker compose up -d`.
- **`ValueError: password cannot be longer than 72 bytes...` na inicialização** — incompatibilidade entre `passlib==1.7.4` e `bcrypt>=4.1`. Já resolvido neste repositório fixando `bcrypt==4.0.1` em `requirements.txt`; se você atualizar essa dependência, reintroduzirá o bug.
- **Login redireciona em loop / `TypeError: unhashable type: 'dict'`** — sintoma de uma versão do Starlette cuja assinatura de `TemplateResponse` mudou para `(request, name, context)`. Todos os `TemplateResponse` deste projeto já usam a assinatura nova; se você adicionar uma nova página, siga o mesmo padrão usado em `app/routers/*.py`.
- **Horas não aparecem para a competência importada** — confira se o `Iteration Path` do export do Azure DevOps realmente contém o mês/ano da competência (ex.: `"Agosto 2026"`, `"2026-08"`); linhas de outros meses são descartadas por design (regra de negócio, não bug).
- **`horas_consumidas` zerado num incidente/requisição** — o cruzamento depende do número do chamado aparecer no campo `Title` das Horas Tereos exatamente no formato `INCxxxxxxx`/`RITMxxxxxxx`/etc. (regex `NUMERO_CHAMADO_REGEX`); variações de formatação (espaços, hífens) não são capturadas.

## Segurança

- Senhas armazenadas com `bcrypt` via `passlib` ([`app/config/security.py`](app/config/security.py)), nunca em texto puro.
- Sessão de servidor assinada por `SECRET_KEY` (`itsdangerous`/`SessionMiddleware`) — **troque o valor padrão antes de qualquer uso fora do ambiente local**.
- Todas as rotas de negócio exigem sessão autenticada via dependência `exigir_login`; não há endpoints de escrita sem autenticação.
- `.gitignore` já exclui `.env`, `uploads/` e arquivos `.xlsx` soltos na raiz para evitar vazamento acidental de credenciais ou dados de clientes no repositório.

## Limitações conhecidas / roadmap

- **SLA de início de atendimento** (15 min / 30 min / 4h por prioridade) está parametrizado em `settings.py`, mas não é calculado — os exports padrão do ServiceNow usados como referência não trazem um campo de "primeira resposta"/"first response time". Adicionar esse cálculo requer mapear a coluna correspondente em `INC_COLS` e uma nova regra em `parsing_utils.py`.
- **Importação de Melhorias** não tem um arquivo de origem dedicado (não especificado na origem do projeto); o cadastro é manual via CRUD em `/anual`.
- Sem testes automatizados (`pytest`) neste momento — a validação foi feita manualmente ponta a ponta (importação CSV, importação `Dados_RAC` consolidado, cálculo de SLA/aging, cruzamento de horas, exportação, CRUD de competências com cascade). Contribuições adicionando uma suíte de testes são bem-vindas.
- Perfil `analista` existe no schema (`usuarios.perfil`) e há uma dependência `exigir_admin` pronta em `security.py`, mas nenhuma rota atual restringe ações apenas a administradores — todo usuário autenticado tem acesso total.
