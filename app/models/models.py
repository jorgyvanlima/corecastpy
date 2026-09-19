from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.config.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    nome = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    senha_hash = Column(String(255), nullable=False)
    perfil = Column(String(20), default="analista")
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


class Competencia(Base):
    __tablename__ = "competencias"

    id = Column(Integer, primary_key=True)
    ano_mes = Column(String(7), unique=True, nullable=False)
    rotulo = Column(String(50), nullable=False)
    status = Column(String(20), default="Aberta")
    total_horas = Column(Numeric(10, 2), default=0)
    total_incidentes = Column(Integer, default=0)
    total_requisicoes = Column(Integer, default=0)
    total_melhorias = Column(Integer, default=0)
    sla_cumprimento = Column(Numeric(5, 2), default=0)
    criado_em = Column(DateTime, default=datetime.utcnow)

    horas = relationship("HorasTereos", cascade="all, delete-orphan", back_populates="competencia")
    incidentes = relationship("Incidente", cascade="all, delete-orphan", back_populates="competencia")
    requisicoes = relationship("Requisicao", cascade="all, delete-orphan", back_populates="competencia")
    melhorias = relationship("Melhoria", cascade="all, delete-orphan", back_populates="competencia")


class HorasTereos(Base):
    __tablename__ = "horas_tereos"

    id = Column(Integer, primary_key=True)
    competencia_id = Column(Integer, ForeignKey("competencias.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text)
    work_item_id = Column(String(50))
    work_item_type = Column(String(50))
    assigned_to = Column(String(150))
    state = Column(String(50))
    grupo_atribuicao = Column(String(100))
    horas = Column(Numeric(10, 2), default=0)
    iteration_path = Column(String(100))
    chamado_associado = Column(String(50))

    competencia = relationship("Competencia", back_populates="horas")


class Incidente(Base):
    __tablename__ = "incidentes"

    id = Column(Integer, primary_key=True)
    competencia_id = Column(Integer, ForeignKey("competencias.id", ondelete="CASCADE"), nullable=False)
    numero = Column(String(50), nullable=False)
    criado_em = Column(DateTime)
    estado = Column(String(50), default="Encerrado")
    atribuicao_a = Column(String(150))
    grupo_atribuicao = Column(String(100))
    business_application = Column(String(150))
    data_ultimo_comentario = Column(DateTime)
    prioridade = Column(String(50))
    duracao_segundos = Column(BigInteger, default=0)
    duracao_negocios_segundos = Column(BigInteger, default=0)
    duracao_horas = Column(Numeric(10, 2), default=0)
    meta_sla_horas = Column(Numeric(10, 2), default=12)
    status_sla = Column(String(20), default="No Prazo")
    dentro_aging_8dias = Column(Boolean, default=True)
    contagem_reaberturas = Column(Integer, default=0)
    horas_consumidas = Column(Numeric(10, 2), default=0)
    descricao_resumida = Column(Text)
    tempo_repasse_minutos = Column(Numeric(10, 2))  # N1 -> N2; NULL quando o export nao traz o dado

    competencia = relationship("Competencia", back_populates="incidentes")


class Requisicao(Base):
    __tablename__ = "requisicoes"

    id = Column(Integer, primary_key=True)
    competencia_id = Column(Integer, ForeignKey("competencias.id", ondelete="CASCADE"), nullable=False)
    numero = Column(String(50), nullable=False)
    classificacao_demanda = Column(String(100))
    complexidade_demanda = Column(String(50))
    criacao_em = Column(DateTime)
    estado = Column(String(50))
    grupo_atribuicao = Column(String(100))
    atribuicao_a = Column(String(150))
    business_application = Column(String(150))
    horas_consumidas = Column(Numeric(10, 2), default=0)

    competencia = relationship("Competencia", back_populates="requisicoes")


class Melhoria(Base):
    __tablename__ = "melhorias"

    id = Column(Integer, primary_key=True)
    competencia_id = Column(Integer, ForeignKey("competencias.id", ondelete="CASCADE"), nullable=False)
    ritm_numero = Column(String(50))
    aplicacao = Column(String(100))
    descricao = Column(Text)
    horas_estimadas = Column(Numeric(10, 2), default=0)
    horas_consumidas = Column(Numeric(10, 2), default=0)
    status = Column(String(50), default="Em Andamento")
    solicitante = Column(String(150))

    competencia = relationship("Competencia", back_populates="melhorias")


class BaselineTrimestral(Base):
    __tablename__ = "baseline_trimestral"

    id = Column(Integer, primary_key=True)
    trimestre = Column(String(10), unique=True, nullable=False)
    saldo_anterior = Column(Numeric(10, 2), default=0)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
