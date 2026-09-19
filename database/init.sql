-- =====================================================================
-- CoreCast - Schema PostgreSQL
-- Portal de Gestao de Atendimentos AMS, Esforco e Apuracao de SLA
-- =====================================================================

-- 1. Usuarios e Autenticacao
CREATE TABLE usuarios (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    senha_hash VARCHAR(255) NOT NULL,
    perfil VARCHAR(20) DEFAULT 'analista', -- 'admin' | 'analista'
    ativo BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Competencias (Anual / Mensal)
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

-- 3. Horas Tereos (Azure DevOps)
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
    chamado_associado VARCHAR(50) -- Extraido via Regex (INC... / RITM...)
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
    prioridade VARCHAR(50), -- Ex: '3 - Media'
    duracao_segundos BIGINT DEFAULT 0,
    duracao_negocios_segundos BIGINT DEFAULT 0,
    duracao_horas NUMERIC(10,2) DEFAULT 0,
    meta_sla_horas NUMERIC(10,2) DEFAULT 12,
    status_sla VARCHAR(20) DEFAULT 'No Prazo', -- 'No Prazo' | 'Atraso'
    dentro_aging_8dias BOOLEAN DEFAULT TRUE,
    contagem_reaberturas INT DEFAULT 0,
    horas_consumidas NUMERIC(10,2) DEFAULT 0,
    descricao_resumida TEXT,
    tempo_repasse_minutos NUMERIC(10,2) -- Handoff N1 -> N2 (NULL se o export nao trouxer o dado)
);

-- 5. Requisicoes (ServiceNow - RITM)
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

-- 6. Posicao de Melhorias & Baseline
CREATE TABLE melhorias (
    id SERIAL PRIMARY KEY,
    competencia_id INT NOT NULL REFERENCES competencias(id) ON DELETE CASCADE,
    ritm_numero VARCHAR(50),
    aplicacao VARCHAR(100),
    descricao TEXT,
    horas_estimadas NUMERIC(10,2) DEFAULT 0,
    horas_consumidas NUMERIC(10,2) DEFAULT 0,
    status VARCHAR(50) DEFAULT 'Em Andamento', -- 'Em Andamento' | 'Em Homologacao' | 'Finalizada'
    solicitante VARCHAR(150)
);

-- 7. Baseline Trimestral (saldo de horas de melhorias que carrega entre trimestres)
CREATE TABLE baseline_trimestral (
    id SERIAL PRIMARY KEY,
    trimestre VARCHAR(10) UNIQUE NOT NULL, -- Ex: '2026-Q3'
    saldo_anterior NUMERIC(10,2) DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indices de Alta Performance
CREATE INDEX idx_horas_comp ON horas_tereos(competencia_id);
CREATE INDEX idx_horas_chamado ON horas_tereos(chamado_associado);
CREATE INDEX idx_inc_comp ON incidentes(competencia_id);
CREATE INDEX idx_inc_num ON incidentes(numero);
CREATE INDEX idx_req_comp ON requisicoes(competencia_id);
CREATE INDEX idx_req_num ON requisicoes(numero);
CREATE INDEX idx_melh_comp ON melhorias(competencia_id);
