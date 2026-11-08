"""Configuração do robô: tudo vem do .env (nunca do código) e tem padrão seguro."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PADRAO = Path(__file__).resolve().parents[2]


def _env(nome: str, padrao: str) -> str:
    valor = os.getenv(nome)
    return padrao if valor is None or valor.strip() == "" else valor.strip()


@dataclass(frozen=True)
class Config:
    raiz: Path

    # integrações
    visao_url: str = "http://localhost:8000"
    visao_timeout_s: float = 20.0
    visao_tentativas: int = 3
    visao_backoff_s: float = 1.0
    visao_limite_circuito: int = 3
    geosampa_wfs_url: str = "http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs"
    geosampa_timeout_s: float = 10.0
    clima_url: str = "https://api.open-meteo.com/v1/forecast"
    clima_timeout_s: float = 10.0
    llm_url: str = ""
    llm_timeout_s: float = 30.0

    # regras de negócio
    raio_poste_m: float = 40.0
    raio_dedup_m: float = 30.0
    ldr_limiar_escuro_lux: float = 5.0
    ldr_limiar_fraco_lux: float = 15.0
    max_lote: int = 200
    max_foto_mb: float = 10.0
    max_idade_relato_dias: int = 30

    # LGPD
    salt_lgpd: str = ""
    retencao_fotos_dias: int = 30

    painel_porta: int = 8001

    # ---- pastas derivadas da raiz ----
    @property
    def pasta_entrada(self) -> Path:
        return self.raiz / "entrada"

    @property
    def pasta_processados(self) -> Path:
        return self.raiz / "processados"

    @property
    def pasta_erros(self) -> Path:
        return self.raiz / "erros"

    @property
    def pasta_saida(self) -> Path:
        return self.raiz / "saida"

    @property
    def pasta_logs(self) -> Path:
        return self.raiz / "logs"

    @property
    def pasta_dados(self) -> Path:
        return self.raiz / "dados"

    @property
    def pasta_fotos(self) -> Path:
        return self.pasta_dados / "fotos"

    @property
    def banco(self) -> Path:
        return self.pasta_dados / "rua_acesa.db"

    @property
    def postes_csv(self) -> Path:
        return self.pasta_dados / "postes_geosampa.csv"

    def criar_pastas(self) -> None:
        for p in (self.pasta_entrada, self.pasta_processados, self.pasta_erros, self.pasta_saida,
                  self.pasta_logs, self.pasta_dados, self.pasta_fotos):
            p.mkdir(parents=True, exist_ok=True)

    def com(self, **alteracoes) -> "Config":
        return replace(self, **alteracoes)

    @classmethod
    def carregar(cls, raiz: Path | None = None) -> "Config":
        raiz = Path(raiz or os.getenv("RUA_ACESA_RAIZ") or RAIZ_PADRAO).resolve()
        load_dotenv(raiz / ".env")
        cfg = cls(
            raiz=raiz,
            visao_url=_env("VISAO_URL", cls.visao_url).rstrip("/"),
            visao_timeout_s=float(_env("VISAO_TIMEOUT_S", str(cls.visao_timeout_s))),
            visao_tentativas=int(_env("VISAO_TENTATIVAS", str(cls.visao_tentativas))),
            visao_backoff_s=float(_env("VISAO_BACKOFF_S", str(cls.visao_backoff_s))),
            visao_limite_circuito=int(_env("VISAO_LIMITE_CIRCUITO", str(cls.visao_limite_circuito))),
            geosampa_wfs_url=_env("GEOSAMPA_WFS_URL", cls.geosampa_wfs_url),
            geosampa_timeout_s=float(_env("GEOSAMPA_TIMEOUT_S", str(cls.geosampa_timeout_s))),
            clima_url=_env("CLIMA_URL", cls.clima_url),
            clima_timeout_s=float(_env("CLIMA_TIMEOUT_S", str(cls.clima_timeout_s))),
            llm_url=_env("LLM_URL", "").rstrip("/"),
            llm_timeout_s=float(_env("LLM_TIMEOUT_S", str(cls.llm_timeout_s))),
            raio_poste_m=float(_env("RAIO_POSTE_M", str(cls.raio_poste_m))),
            raio_dedup_m=float(_env("RAIO_DEDUP_M", str(cls.raio_dedup_m))),
            ldr_limiar_escuro_lux=float(_env("LDR_LIMIAR_ESCURO_LUX", str(cls.ldr_limiar_escuro_lux))),
            ldr_limiar_fraco_lux=float(_env("LDR_LIMIAR_FRACO_LUX", str(cls.ldr_limiar_fraco_lux))),
            max_lote=int(_env("MAX_LOTE", str(cls.max_lote))),
            max_foto_mb=float(_env("MAX_FOTO_MB", str(cls.max_foto_mb))),
            max_idade_relato_dias=int(_env("MAX_IDADE_RELATO_DIAS", str(cls.max_idade_relato_dias))),
            salt_lgpd=_env("SALT_LGPD", ""),
            retencao_fotos_dias=int(_env("RETENCAO_FOTOS_DIAS", str(cls.retencao_fotos_dias))),
            painel_porta=int(_env("PAINEL_PORTA", str(cls.painel_porta))),
        )
        cfg.criar_pastas()
        if not cfg.salt_lgpd:
            cfg = cfg.com(salt_lgpd=_salt_persistido(cfg.pasta_dados / ".salt"))
        return cfg


def _salt_persistido(caminho: Path) -> str:
    """Sem SALT_LGPD no .env, gera um salt aleatório uma única vez (fora do git)."""
    if caminho.exists():
        return caminho.read_text().strip()
    salt = secrets.token_hex(32)
    caminho.write_text(salt)
    try:
        caminho.chmod(0o600)
    except OSError:
        pass
    return salt
