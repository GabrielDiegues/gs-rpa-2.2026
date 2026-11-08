"""Contratos de dados do robô: entrada (relato), resposta da visão e estados."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FUSO_SP = ZoneInfo("America/Sao_Paulo")


class StatusRelato(StrEnum):
    PENDENTE_VISAO = "pendente_visao"      # visão fora do ar: reprocessado na próxima execução
    VINCULADO = "vinculado"                # virou (ou reforçou) uma solicitação
    ARQUIVADO = "arquivado"                # não procede (IA não confirmou / leitura adequada)
    REJEITADO_VISAO = "rejeitado_visao"    # a visão recusou a foto (formato/tamanho)


class StatusSolicitacao(StrEnum):
    AGUARDANDO_REVISAO = "aguardando_revisao"
    ENVIADA = "enviada"            # aprovada por uma pessoa e encaminhada à Prefeitura (SP156)
    REJEITADA = "rejeitada"
    RESOLVIDA = "resolvida"        # poste religado


STATUS_ABERTOS = (StatusSolicitacao.AGUARDANDO_REVISAO, StatusSolicitacao.ENVIADA)


class Evidencia(StrEnum):
    CONFIRMADA = "confirmada"      # YOLO confirmou poste apagado
    SENSOR = "sensor"              # só a leitura do robô (LDR) indicou escuro
    INCONCLUSIVA = "inconclusiva"  # foto não prova (dia / nenhum poste confiável)


# ------------------------------------------------------------------ entrada
class LeituraRobo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispositivo_id: str = Field(min_length=1, max_length=64)
    luminosidade_lux: float = Field(ge=0, le=200_000)
    classificacao: Literal["adequado", "fraco", "escuro"] | None = Field(
        default=None, description="classificação feita no próprio robô (o RPA reconfere pelos limiares)")


class RelatoEntrada(BaseModel):
    """Formato do arquivo JSON depositado em entrada/ pela API central ou pelo robô."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    origem: Literal["cidadao", "robo"]
    criado_em: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    descricao: str | None = Field(default=None, max_length=500)
    foto: str | None = Field(default=None, max_length=200,
                             description="nome do arquivo da foto, na mesma pasta do JSON")
    contato: str | None = Field(default=None, max_length=120,
                                description="opcional; nunca é gravado em claro (LGPD)")
    leitura: LeituraRobo | None = None

    @field_validator("criado_em")
    @classmethod
    def _com_fuso(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=FUSO_SP) if v.tzinfo is None else v

    @field_validator("foto")
    @classmethod
    def _sem_caminho(cls, v: str | None) -> str | None:
        if v and ("/" in v or "\\" in v or v.startswith(".")):
            raise ValueError("foto deve ser só o nome do arquivo, sem caminho")
        return v

    @model_validator(mode="after")
    def _por_origem(self) -> "RelatoEntrada":
        if self.origem == "cidadao" and not self.foto:
            raise ValueError("relato de cidadão exige foto")
        if self.origem == "robo" and self.leitura is None:
            raise ValueError("relato do robô exige o bloco 'leitura'")
        return self


# ------------------------------------------------------------------ visão (espelha app/schemas.py)
class Deteccao(BaseModel):
    classe: Literal["poste_aceso", "poste_apagado"]
    confianca: float = Field(ge=0, le=1)
    bbox: list[float]


class ResultadoVisao(BaseModel):
    veredito: Literal["confirmado", "nao_confirmado", "inconclusivo"]
    motivo: str
    cena: Literal["dia", "noite"]
    brilho_medio: float
    deteccoes: list[Deteccao]
    largura: int
    altura: int
    modelo: str
    tempo_ms: float

    @property
    def confianca_apagado(self) -> float:
        return max((d.confianca for d in self.deteccoes if d.classe == "poste_apagado"), default=0.0)
