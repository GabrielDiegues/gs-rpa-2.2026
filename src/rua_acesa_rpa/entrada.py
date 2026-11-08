"""Pasta de entrada: leitura do lote e movimentação dos arquivos já tratados.

Cada relato é um JSON em entrada/ (a foto, se houver, fica ao lado). Depois de
tratado, o par JSON+foto vai para processados/<run_id>/ ou erros/<run_id>/
(com um .erro.txt explicando o motivo) — nada fica perdido nem é lido duas vezes.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def listar_lote(pasta: Path, limite: int) -> tuple[list[Path], int]:
    """Arquivos .json em ordem de chegada (mtime, depois nome). Retorna (lote, restantes)."""
    arquivos = sorted((p for p in pasta.glob("*.json") if p.is_file()),
                      key=lambda p: (p.stat().st_mtime, p.name))
    return arquivos[:limite], max(0, len(arquivos) - limite)


def foto_referenciada(arquivo_json: Path) -> Path | None:
    """Tenta descobrir a foto citada no JSON mesmo que ele seja inválido (para movê-la junto)."""
    try:
        dados = json.loads(arquivo_json.read_text(encoding="utf-8"))
        nome = dados.get("foto") if isinstance(dados, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(nome, str) and nome and "/" not in nome and "\\" not in nome and not nome.startswith("."):
        caminho = arquivo_json.parent / nome
        return caminho if caminho.is_file() else None
    return None


def _destino_livre(pasta: Path, nome: str) -> Path:
    destino = pasta / nome
    i = 1
    while destino.exists():
        destino = pasta / f"{Path(nome).stem}__{i}{Path(nome).suffix}"
        i += 1
    return destino


def mover_para(arquivo_json: Path, pasta_destino: Path, nota: str | None = None,
               sufixo_nota: str = ".erro.txt") -> Path:
    pasta_destino.mkdir(parents=True, exist_ok=True)
    foto = foto_referenciada(arquivo_json)
    destino_json = _destino_livre(pasta_destino, arquivo_json.name)
    shutil.move(str(arquivo_json), destino_json)
    if foto is not None:
        # a mesma foto pode ser citada por outro JSON ainda na fila: copia em vez de mover
        outros = [p for p in arquivo_json.parent.glob("*.json") if foto_referenciada(p) == foto]
        destino_foto = _destino_livre(pasta_destino, foto.name)
        (shutil.copy2 if outros else shutil.move)(str(foto), destino_foto)
    if nota:
        destino_json.with_suffix(sufixo_nota).write_text(nota + "\n", encoding="utf-8")
    return destino_json
