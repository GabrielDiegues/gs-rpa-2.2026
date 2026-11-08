"""Regras de validação do relato (etapa 1 do fluxo). Retornam mensagens claras para erros/."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from rua_acesa_rpa.geo import dentro_de_sp
from rua_acesa_rpa.modelos import RelatoEntrada
from rua_acesa_rpa.repositorio import agora

EXTENSOES_FOTO = {".jpg", ".jpeg", ".png", ".webp"}
TOLERANCIA_FUTURO = timedelta(minutes=10)


class RelatoInvalido(Exception):
    """O arquivo não pode virar relato. A mensagem vai para erros/<arquivo>.erro.txt."""


@dataclass
class RelatoValidado:
    relato: RelatoEntrada
    arquivo_json: Path
    foto: Path | None


def _resumir_erros_pydantic(e: ValidationError) -> str:
    partes = []
    for err in e.errors():
        campo = ".".join(str(p) for p in err["loc"]) or "relato"
        partes.append(f"{campo}: {err['msg']}")
    return "; ".join(partes)


def ler_json(arquivo: Path) -> dict:
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise RelatoInvalido("arquivo não está em UTF-8") from e
    if not texto.strip():
        raise RelatoInvalido("arquivo vazio")
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as e:
        raise RelatoInvalido(f"JSON inválido (linha {e.lineno}, coluna {e.colno}): {e.msg}") from e
    if not isinstance(dados, dict):
        raise RelatoInvalido("o JSON deve ser um objeto com os campos do relato")
    return dados


def validar_foto(caminho: Path, max_mb: float) -> None:
    if caminho.suffix.lower() not in EXTENSOES_FOTO:
        raise RelatoInvalido(f"formato de foto não suportado ({caminho.suffix}); use JPEG, PNG ou WebP")
    if not caminho.is_file():
        raise RelatoInvalido(f"foto '{caminho.name}' não encontrada ao lado do JSON")
    tamanho_mb = caminho.stat().st_size / (1024 * 1024)
    if tamanho_mb == 0:
        raise RelatoInvalido(f"foto '{caminho.name}' está vazia")
    if tamanho_mb > max_mb:
        raise RelatoInvalido(f"foto com {tamanho_mb:.1f} MB excede o limite de {max_mb:.0f} MB")
    try:
        with Image.open(caminho) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise RelatoInvalido(f"foto '{caminho.name}' corrompida ou ilegível") from e


def validar_relato(arquivo: Path, *, max_foto_mb: float, max_idade_dias: int) -> RelatoValidado:
    dados = ler_json(arquivo)
    try:
        relato = RelatoEntrada.model_validate(dados)
    except ValidationError as e:
        raise RelatoInvalido(f"campos inválidos — {_resumir_erros_pydantic(e)}") from e

    if not dentro_de_sp(relato.latitude, relato.longitude):
        raise RelatoInvalido(
            f"coordenada ({relato.latitude:.3f}, {relato.longitude:.3f}) fora do município de São Paulo")

    agora_sp = agora()
    if relato.criado_em > agora_sp + TOLERANCIA_FUTURO:
        raise RelatoInvalido("data do relato está no futuro")
    if relato.criado_em < agora_sp - timedelta(days=max_idade_dias):
        raise RelatoInvalido(f"relato com mais de {max_idade_dias} dias; registre um novo relato")

    foto = None
    if relato.foto:
        foto = arquivo.parent / relato.foto
        validar_foto(foto, max_foto_mb)
    return RelatoValidado(relato=relato, arquivo_json=arquivo, foto=foto)
