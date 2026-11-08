"""Persistência em SQLite (biblioteca padrão): relatos, solicitações, execuções e auditoria.

O banco é o "contrato" compartilhado com o painel de revisão; os exports em saida/
são o contrato com o mapa e com o pipeline de dados (Airflow/Databricks).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from rua_acesa_rpa.modelos import FUSO_SP, STATUS_ABERTOS

ESQUEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    run_id TEXT PRIMARY KEY,
    tipo TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fim TEXT,
    status TEXT NOT NULL DEFAULT 'em_andamento',
    resumo_json TEXT
);

CREATE TABLE IF NOT EXISTS solicitacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo TEXT UNIQUE,
    poste_placa TEXT,
    poste_endereco TEXT,
    poste_tipo TEXT,
    poste_fonte TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    status TEXT NOT NULL,
    evidencia TEXT NOT NULL,
    prioridade_score INTEGER NOT NULL DEFAULT 0,
    prioridade_faixa TEXT NOT NULL DEFAULT 'baixa',
    prioridade_motivos TEXT NOT NULL DEFAULT '[]',
    qtd_relatos INTEGER NOT NULL DEFAULT 0,
    qtd_relatos_cidadao INTEGER NOT NULL DEFAULT 0,
    corroborado_robo INTEGER NOT NULL DEFAULT 0,
    indicio_reparo INTEGER NOT NULL DEFAULT 0,
    clima_json TEXT,
    texto TEXT,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    primeiro_relato_em TEXT,
    revisado_por TEXT,
    revisado_em TEXT,
    motivo_revisao TEXT,
    resolvido_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_sol_placa_status ON solicitacoes(poste_placa, status);

CREATE TABLE IF NOT EXISTS relatos (
    id TEXT PRIMARY KEY,
    origem TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    recebido_em TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    descricao TEXT,
    foto_sha256 TEXT,
    foto_arquivo TEXT,
    contato_hash TEXT,
    contato_mascarado TEXT,
    dispositivo_id TEXT,
    leitura_lux REAL,
    classificacao_robo TEXT,
    classificacao_rpa TEXT,
    veredito TEXT,
    motivo TEXT,
    cena TEXT,
    confianca_apagado REAL,
    status TEXT NOT NULL,
    solicitacao_id INTEGER REFERENCES solicitacoes(id),
    poste_placa TEXT,
    distancia_poste_m REAL,
    tentativas_visao INTEGER NOT NULL DEFAULT 0,
    run_id TEXT,
    atualizado_em TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_relatos_foto ON relatos(foto_sha256) WHERE foto_sha256 IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_relatos_status ON relatos(status);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    nivel TEXT NOT NULL,
    etapa TEXT NOT NULL,
    relato_id TEXT,
    solicitacao_id INTEGER,
    mensagem TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notificacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    relato_id TEXT NOT NULL,
    contato_hash TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente_envio'
);

CREATE TABLE IF NOT EXISTS postes_cache (
    placa TEXT PRIMARY KEY,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    endereco TEXT,
    tipo TEXT,
    consultado_em TEXT NOT NULL
);
"""


def agora() -> datetime:
    return datetime.now(FUSO_SP)


def agora_iso() -> str:
    return agora().isoformat(timespec="seconds")


class Repositorio:
    def __init__(self, caminho: Path):
        self.caminho = caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(caminho, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(ESQUEMA)

    def fechar(self) -> None:
        self.conn.close()

    @contextmanager
    def transacao(self) -> Iterator[sqlite3.Connection]:
        """Tudo ou nada por relato: um erro no meio não deixa estado pela metade."""
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ---------------------------------------------------------------- genéricos
    def _inserir(self, tabela: str, dados: dict[str, Any]) -> int:
        cols = ", ".join(dados)
        marc = ", ".join("?" for _ in dados)
        cur = self.conn.execute(f"INSERT INTO {tabela} ({cols}) VALUES ({marc})", tuple(dados.values()))
        return int(cur.lastrowid)

    def _atualizar(self, tabela: str, chave: str, valor: Any, dados: dict[str, Any]) -> None:
        sets = ", ".join(f"{c} = ?" for c in dados)
        self.conn.execute(f"UPDATE {tabela} SET {sets} WHERE {chave} = ?", (*dados.values(), valor))

    # ---------------------------------------------------------------- execuções
    def iniciar_execucao(self, run_id: str, tipo: str) -> None:
        self._inserir("execucoes", {"run_id": run_id, "tipo": tipo, "inicio": agora_iso()})

    def finalizar_execucao(self, run_id: str, status: str, resumo: dict) -> None:
        self._atualizar("execucoes", "run_id", run_id,
                        {"fim": agora_iso(), "status": status,
                         "resumo_json": json.dumps(resumo, ensure_ascii=False)})

    def execucoes(self, limite: int = 20) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM execucoes ORDER BY inicio DESC LIMIT ?", (limite,))
        out = []
        for r in rows:
            d = dict(r)
            d["resumo"] = json.loads(d.pop("resumo_json") or "{}")
            out.append(d)
        return out

    # ---------------------------------------------------------------- relatos
    def relato(self, relato_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM relatos WHERE id = ?", (relato_id,)).fetchone()
        return dict(r) if r else None

    def relato_por_foto(self, sha256: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM relatos WHERE foto_sha256 = ?", (sha256,)).fetchone()
        return dict(r) if r else None

    def inserir_relato(self, dados: dict[str, Any]) -> None:
        dados = {**dados, "atualizado_em": agora_iso()}
        self._inserir("relatos", dados)

    def atualizar_relato(self, relato_id: str, **dados: Any) -> None:
        self._atualizar("relatos", "id", relato_id, {**dados, "atualizado_em": agora_iso()})

    def relatos_por_status(self, status: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM relatos WHERE status = ? ORDER BY criado_em", (status,))
        return [dict(r) for r in rows]

    def relatos_da_solicitacao(self, solicitacao_id: int) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM relatos WHERE solicitacao_id = ? ORDER BY criado_em",
                                 (solicitacao_id,))
        return [dict(r) for r in rows]

    def todos_relatos(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM relatos ORDER BY criado_em")]

    # ---------------------------------------------------------------- solicitações
    def solicitacao(self, sol_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM solicitacoes WHERE id = ?", (sol_id,)).fetchone()
        return dict(r) if r else None

    def inserir_solicitacao(self, dados: dict[str, Any]) -> int:
        ts = agora_iso()
        return self._inserir("solicitacoes", {**dados, "criado_em": ts, "atualizado_em": ts})

    def atualizar_solicitacao(self, sol_id: int, **dados: Any) -> None:
        self._atualizar("solicitacoes", "id", sol_id, {**dados, "atualizado_em": agora_iso()})

    def solicitacao_aberta_por_placa(self, placa: str) -> dict | None:
        marc = ", ".join("?" for _ in STATUS_ABERTOS)
        r = self.conn.execute(
            f"SELECT * FROM solicitacoes WHERE poste_placa = ? AND status IN ({marc}) "
            "ORDER BY criado_em LIMIT 1", (placa, *STATUS_ABERTOS)).fetchone()
        return dict(r) if r else None

    def solicitacoes_abertas_sem_poste(self) -> list[dict]:
        marc = ", ".join("?" for _ in STATUS_ABERTOS)
        rows = self.conn.execute(
            f"SELECT * FROM solicitacoes WHERE poste_placa IS NULL AND status IN ({marc})", STATUS_ABERTOS)
        return [dict(r) for r in rows]

    def solicitacoes(self, status: list[str] | None = None) -> list[dict]:
        if status:
            marc = ", ".join("?" for _ in status)
            rows = self.conn.execute(
                f"SELECT * FROM solicitacoes WHERE status IN ({marc}) "
                "ORDER BY prioridade_score DESC, criado_em", tuple(status))
        else:
            rows = self.conn.execute("SELECT * FROM solicitacoes ORDER BY prioridade_score DESC, criado_em")
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- auditoria / outbox
    def inserir_evento(self, dados: dict[str, Any]) -> None:
        self._inserir("eventos", dados)

    def eventos(self, solicitacao_id: int | None = None, limite: int = 200) -> list[dict]:
        if solicitacao_id is None:
            rows = self.conn.execute("SELECT * FROM eventos ORDER BY id DESC LIMIT ?", (limite,))
        else:
            rows = self.conn.execute(
                "SELECT * FROM eventos WHERE solicitacao_id = ? OR relato_id IN "
                "(SELECT id FROM relatos WHERE solicitacao_id = ?) ORDER BY id", (solicitacao_id, solicitacao_id))
        return [dict(r) for r in rows]

    def inserir_notificacao(self, relato_id: str, contato_hash: str, mensagem: str) -> None:
        self._inserir("notificacoes", {"ts": agora_iso(), "relato_id": relato_id,
                                       "contato_hash": contato_hash, "mensagem": mensagem})

    def notificacoes(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM notificacoes ORDER BY id")]

    # ---------------------------------------------------------------- cache de postes
    def salvar_postes_cache(self, postes: list[dict]) -> None:
        ts = agora_iso()
        self.conn.executemany(
            "INSERT INTO postes_cache (placa, latitude, longitude, endereco, tipo, consultado_em) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(placa) DO UPDATE SET latitude=excluded.latitude, "
            "longitude=excluded.longitude, endereco=excluded.endereco, tipo=excluded.tipo, "
            "consultado_em=excluded.consultado_em",
            [(p["placa"], p["latitude"], p["longitude"], p.get("endereco"), p.get("tipo"), ts) for p in postes])

    def postes_cache_na_caixa(self, lat_min: float, lon_min: float, lat_max: float, lon_max: float) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM postes_cache WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?",
            (lat_min, lat_max, lon_min, lon_max))
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- indicadores (ficha técnica)
    def contagem(self, sql: str, params: tuple = ()) -> int:
        return int(self.conn.execute(sql, params).fetchone()[0] or 0)
