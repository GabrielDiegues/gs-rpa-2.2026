"""Logs de auditoria: cada passo vira uma linha JSON (logs/rpa_AAAA-MM-DD.jsonl),
um evento no banco (consultável pelo painel) e uma linha legível no terminal.

Nada de dado pessoal: as mensagens passam por lgpd.sanitizar e coordenadas são
arredondadas para ~100 m antes de entrar no log.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from rua_acesa_rpa.lgpd import sanitizar
from rua_acesa_rpa.repositorio import Repositorio, agora, agora_iso

_NIVEIS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARN": logging.WARNING, "ERROR": logging.ERROR}

logger = logging.getLogger("rua_acesa_rpa")


def configurar_console(verboso: bool = False) -> None:
    if logger.handlers:
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    logger.addHandler(h)
    logger.setLevel(logging.DEBUG if verboso else logging.INFO)
    logger.propagate = False


class Auditoria:
    def __init__(self, run_id: str, pasta_logs: Path, repo: Repositorio):
        self.run_id = run_id
        self.pasta_logs = pasta_logs
        self.repo = repo
        pasta_logs.mkdir(parents=True, exist_ok=True)

    @property
    def arquivo(self) -> Path:
        return self.pasta_logs / f"rpa_{agora():%Y-%m-%d}.jsonl"

    def registrar(self, etapa: str, mensagem: str, nivel: str = "INFO", relato_id: str | None = None,
                  solicitacao_id: int | None = None, **extra) -> None:
        nivel = nivel.upper()
        mensagem = sanitizar(str(mensagem))
        extra = {k: (sanitizar(v) if isinstance(v, str) else v) for k, v in extra.items()}
        ts = agora_iso()
        linha = {"ts": ts, "run_id": self.run_id, "nivel": nivel, "etapa": etapa,
                 "relato_id": relato_id, "solicitacao_id": solicitacao_id, "mensagem": mensagem, **extra}
        try:
            with self.arquivo.open("a", encoding="utf-8") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")
        except OSError as e:  # disco cheio / permissão: avisa no terminal, não derruba o robô
            logger.error("falha ao gravar log em arquivo: %s", e)
        try:
            self.repo.inserir_evento({"ts": ts, "run_id": self.run_id, "nivel": nivel, "etapa": etapa,
                                      "relato_id": relato_id, "solicitacao_id": solicitacao_id,
                                      "mensagem": mensagem})
        except Exception as e:  # noqa: BLE001 — auditoria nunca pode quebrar o fluxo principal
            logger.error("falha ao gravar evento no banco: %s", e)
        ref = f"[{relato_id}] " if relato_id else ""
        logger.log(_NIVEIS.get(nivel, logging.INFO), "%-13s %s%s", etapa, ref, mensagem)
