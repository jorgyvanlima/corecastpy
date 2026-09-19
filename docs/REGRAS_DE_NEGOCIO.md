# CoreCast — Regras de Negócio

Documento de referência de **como cada número do CoreCast é calculado**. Serve para analistas conferirem os indicadores e para quem for evoluir o código saber onde cada regra mora.

> Última atualização: 19/09/2026. Fonte da verdade: o código. Cada seção indica o arquivo onde a regra está implementada.

## Sumário

1. [Glossário](#1-glossário)
2. [Fontes de dados e importação](#2-fontes-de-dados-e-importação)
3. [SLA, aging e reabertura](#3-sla-aging-e-reabertura)
4. [Dashboard mensal](#4-dashboard-mensal)
5. [Visão anual e baseline de melhorias](#5-visão-anual-e-baseline-de-melhorias)
6. [Parâmetros configuráveis](#6-parâmetros-configuráveis)
7. [Limitações e decisões em aberto](#7-limitações-e-decisões-em-aberto)

---

## 1. Glossário

| Termo | Significado |
|---|---|
| **Competência** | Um mês de apuração (ex.: `2026-08`, rótulo "Agosto/2026"). Todos os dados pertencem a uma competência. |
| **INC / RITM** | Incidente / item de requisição do ServiceNow. |
| **PRB, CHG, SCTASK, TASK** | Outros tipos de chamado (problema, mudança, tarefas). Aparecem nas horas do Azure DevOps. |
| **Horas Tereos** | Apontamento de esforço exportado do Azure DevOps. |
| **N1 / N2** | Primeiro nível (triagem e encaminhamento) e segundo nível (resolução). O SLA corre enquanto o chamado está no N2. |
| **SQUAD** | O grupo de atribuição normalizado do incidente (ex.: `PowerPlatform`, `RPA`, `Talend`). |
| **Aging** | Idade do incidente até a resolução; o limite é 8 dias. |

## 2. Fontes de dados e importação

Implementação: [`app/services/import_service.py`](../app/services/import_service.py) e [`app/services/parsing_utils.py`](../app/services/parsing_utils.py).

1. **Três origens por competência:** Horas Tereos, Incidentes e Requisições — enviadas separadas ou num consolidado `Dados_RAC` (que tem precedência).
2. **Importação idempotente:** antes de gravar, apaga tudo da competência. Reimportar nunca duplica.
3. **Leitura por nome de cabeçalho**, ignorando acento e caixa, nunca por posição de coluna.
4. **Filtro de competência nas horas:** só entra a linha cujo `Iteration Path` corresponde ao mês/ano importado.
5. **Vínculo horas ↔ chamado:** o número do chamado é extraído do título da linha de horas pela regex `INC\d+|RITM\d+|PRB\d+|CHG\d+|SCTASK\d+|TASK\d+`. As horas do mesmo chamado são somadas e gravadas em `horas_consumidas` do incidente/requisição.
6. **Normalização do grupo de atribuição:** remove tudo até o primeiro `_CAST_` (`BR_CTR_L3_CAST_PowerPlatform` → `PowerPlatform`).
7. **Repasse N1 → N2 (opcional):** se o export trouxer a data do repasse ou o tempo até o repasse, calcula `tempo_repasse_minutos` (ver [4.6](#46-diagnóstico-de-fluxo-e-atrito-handoff-n1--n2)).

Ao final, os totais da competência (`total_horas`, `total_incidentes`, `total_requisicoes`, `sla_cumprimento`) são recalculados.

## 3. SLA, aging e reabertura

Implementação: [`app/services/parsing_utils.py`](../app/services/parsing_utils.py) e [`app/config/settings.py`](../app/config/settings.py).

**Meta de finalização por prioridade**

| Prioridade | Meta | Variável |
|---|---|---|
| 1 — Crítica | 3 h | — |
| 2 — Alta | 4 h | — |
| 3 — Média | 12 h | `SLA_META_P3_HORAS` |
| 4 — Baixa | 32 h | `SLA_META_P4_HORAS` |

Prioridade não reconhecida é tratada como 3.

**Duração do incidente (em horas)**

```
duracao_horas = duração em horas informada, se > 0
              = duração de negócios (s) / 21600, senão      (6 h úteis por dia)
              = duração corrida (s) / 3600, senão
              = 0
```

**Status de SLA e aging**

```
status_sla         = "No Prazo" se duracao_horas <= meta da prioridade, senão "Atraso"
dentro_aging_8dias = duracao_horas <= 192   (8 dias × 24 h)
```

**Indicadores executivos** (contra o total de incidentes da competência)

| Indicador | Fórmula | Meta |
|---|---|---|
| Eficiência de SLA | incidentes "No Prazo" ÷ total × 100 | ≥ 95% |
| Aging 8 dias | incidentes dentro do aging ÷ total × 100 | = 100% |
| Taxa de reabertura | Σ reaberturas ÷ total de incidentes × 100 | ≤ 5% |
| Total de horas | Σ horas Tereos da competência | — |

Metas em `SLA_META_EFICIENCIA_PERCENTUAL`, `SLA_META_AGING_PERCENTUAL` e `SLA_META_REABERTURA_PERCENTUAL`. O card fica **verde** quando a meta é atingida e **vermelho** quando não.

## 4. Dashboard mensal

Implementação: [`app/routers/dashboard.py`](../app/routers/dashboard.py) (cálculos) e [`app/templates/dashboard.html`](../app/templates/dashboard.html) (apresentação). A página segue a ordem abaixo.

### 4.1 Cartões de topo (4 KPIs)

Eficiência de SLA, Aging 8 dias, Taxa de reabertura e Total de horas, conforme a [seção 3](#3-sla-aging-e-reabertura). Cada card mostra o nome do indicador, o valor (animado), um medidor, a meta e uma frase explicativa. O card de horas mostra também a quantidade de incidentes e de requisições.

### 4.2 Análise de esforço (4 gráficos em 2×2)

Todos usam colunas verticais com o valor no topo.

**a) Horas por Aplicação** — top 10 aplicações por horas totais.
- A aplicação de cada linha de horas vem do **chamado citado no título**: procura-se o número em incidentes e requisições e usa-se o `business_application` dele.
- Horas sem chamado, ou cujo chamado não tem aplicação, entram em **"Sem aplicacao"**.

**b) Atendimento por Classificação / Hora** — soma de horas em cinco categorias:

| Categoria | Regra |
|---|---|
| Requisições | chamado `RITM` cuja classificação **não** é melhoria |
| Melhorias | chamado `RITM` cuja `classificacao_demanda` contém "melhoria" |
| Incidentes | chamado `INC` |
| Outras filas | qualquer outro chamado (`PRB`, `CHG`, `SCTASK`, `TASK`) |
| Sem chamado | linha de horas sem número de chamado no título |

**c) Atendimento por Aplicação** — **quantidade de chamados** (incidentes + requisições) por aplicação, top 10. Chamados sem aplicação vão para "Sem aplicacao".

**d) Incidentes: % Eficiência por SQUAD** — por grupo de atribuição, duas colunas:
- **Total de incidentes** do squad;
- **Encerrados dentro do SLA:** estado `Encerrado`, `Resolvido` ou `Fechado` **e** `status_sla = "No Prazo"`.

O tooltip da segunda coluna mostra o percentual (`encerrados no prazo ÷ total`). Squads ordenados por volume.

### 4.3 Visão de SLA (3 gráficos)

- **SLA por Prioridade:** incidentes no prazo × em atraso, empilhados por prioridade.
- **Distribuição SLA:** rosca no prazo × atraso, com o total de incidentes no centro.
- **Horas por Grupo de Atribuição:** top 10 grupos por horas apontadas.

### 4.4 L2 em Números

Três cartões:

1. **Total de Incidentes Analisados** — total da competência, com a divisão no prazo × em atraso.
2. **Eficiência Global (cumprimento de SLA)** — medidor semicircular; mesma fórmula da eficiência de SLA.
3. **Resolução de Aging dentro de 8 dias** — medidor semicircular; mesma fórmula do aging.

Os valores são os mesmos dos KPIs de topo, para que os números batam em toda a página.

### 4.5 Ranking de Aplicações

Painel "Panorama de Incidentes" — considera **apenas incidentes** com aplicação cadastrada.

- **Ordem:** por quantidade de incidentes, desempate por nome. Os 3 primeiros formam o pódio (2º, 1º, 3º); o 4º ao 6º aparecem em cartões abaixo.
- **Por aplicação:**
  - *Chamados* = incidentes da aplicação;
  - *Horas* = soma das horas Tereos cujo chamado é um incidente da aplicação;
  - *% de volume* = incidentes da aplicação ÷ total de incidentes da competência.
- **Nível (4º ao 6º):** `Alta` se % ≥ 10; `Moderada` se % ≥ 3; `Estável` abaixo disso. Limites em `NIVEL_ALTA_PCT` e `NIVEL_MODERADA_PCT`.
- **Barra de chamados (4º ao 6º):** proporcional ao 4º colocado, para não ficar minúscula perto do 1º.
- **Falhas recorrentes:** *aproximação automática*, não uma classificação oficial. Das descrições resumidas dos incidentes da aplicação, contam-se as combinações de duas palavras (e, na falta de repetição, palavras soltas) que mais se repetem, ignorando palavras comuns. Mostra até 2 temas com a contagem, ex.: `Meio ambiente (12x)`. Quando nada se repete, mostra a primeira descrição.

### 4.6 Diagnóstico de Fluxo e Atrito (handoff N1 → N2)

Mede quantos incidentes foram repassados do N1 para o N2 **depois do limite de 30 minutos**, o que já chega ao N2 com o relógio de SLA comprometido.

```
tempo_repasse_minutos = data_do_repasse − data_de_abertura      (em minutos)
                        ou o "tempo até o repasse" informado no export, convertido para minutos

incidentes em atraso  = COUNT( tempo_repasse_minutos > LIMITE_REPASSE_N2_MINUTOS )
impacto sistêmico (%) = incidentes em atraso ÷ total de incidentes da competência × 100
"Soma mensal"         = quebra dos incidentes em atraso por prioridade (P1 + P2 + P3 + P4)
```

- O limite padrão é **30 min** (`LIMITE_REPASSE_N2_MINUTOS`).
- Incidentes **sem** o dado de repasse não entram na contagem de atraso.
- **Sem nenhum dado de repasse na competência**, a seção mostra "Sem dado de repasse N1 → N2" e explica como preencher (ver [seção 7](#7-limitações-e-decisões-em-aberto)).
- Os textos "Impacto Sistêmico" e "Takeaway" são preenchidos com os números calculados; o Takeaway é um texto fixo de orientação.

### 4.7 Top 10 Incidentes em Atraso

Incidentes com `status_sla = "Atraso"`, ordenados pelo **excesso** (`duracao_horas − meta_sla_horas`), do maior para o menor. A barra de excesso é proporcional ao maior excesso da lista.

## 5. Visão anual e baseline de melhorias

Implementação: [`app/routers/anual.py`](../app/routers/anual.py).

- Agrega as competências do ano em 4 trimestres (Q1 jan–mar, Q2 abr–jun, Q3 jul–set, Q4 out–dez), recalculando eficiência, aging e reabertura por trimestre.
- **Baseline de melhorias** por trimestre: `saldo_atualizado = MAX(0, saldo_anterior − horas_estimadas_no_periodo)`, onde as horas estimadas são a soma de `melhorias.horas_estimadas` das competências do trimestre.
- As melhorias são cadastradas manualmente na própria página (não há arquivo de importação para elas).
- Excluir uma competência remove em cascata horas, incidentes, requisições e melhorias.

## 6. Parâmetros configuráveis

| Variável | Padrão | Efeito |
|---|---|---|
| `SLA_META_P3_HORAS` | 12 | Meta de SLA da prioridade 3 |
| `SLA_META_P4_HORAS` | 32 | Meta de SLA da prioridade 4 |
| `LIMITE_REPASSE_N2_MINUTOS` | 30 | Acima disso o repasse N1 → N2 conta como atraso |
| `SECRET_KEY` | (dev) | Assinatura da sessão |
| `ADMIN_EMAIL` / `ADMIN_SENHA` | admin padrão | Usuário criado na primeira execução |

Metas de eficiência (95%), aging (100%) e reabertura (5%), limite de aging (192 h) e conversão de horas úteis (21600 s) ficam em [`app/config/settings.py`](../app/config/settings.py).

## 7. Limitações e decisões em aberto

- **Repasse N1 → N2 sem dado de origem.** O export atual do ServiceNow não traz data de repasse. O sistema aceita colunas opcionais (`Repassado em`, `Data de repasse`, `Tempo de repasse`, `Time to assign` e variações — lista completa em `INC_COLS`), mas até o export incluir uma delas, o diagnóstico fica em estado "sem dado". Depois de incluir a coluna, é preciso **reimportar a competência**.
- **SLA de início de atendimento** (15 min / 30 min / 4 h por prioridade) está parametrizado, mas **não é calculado** por falta de campo de primeira resposta.
- **Falhas recorrentes** no ranking são uma aproximação por palavras repetidas. Para temas fiéis, seria necessária uma tabela de temas mantida pela equipe ou classificação assistida por IA.
- **Faixas de nível** (Alta/Moderada/Estável) e a definição de "encerrado dentro do prazo" foram escolhas de implementação; ajustar se o contrato definir outra regra.
- **SQUAD** é o grupo de atribuição do incidente, não uma entidade própria.
- Gráficos e cartões que dependem de aplicação mostram "Sem aplicacao" para chamados sem esse campo; a qualidade do dado no ServiceNow afeta diretamente esses números.
