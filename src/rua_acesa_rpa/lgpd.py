"""Proteção de dados pessoais (LGPD by design).

- O contato opcional do cidadão nunca é persistido em claro: guardamos um hash
  HMAC-SHA256 (com salt fora do código) e uma versão mascarada para exibição.
- A foto é regravada sem metadados (EXIF/GPS do celular) antes de ser guardada.
- Mensagens de log passam por um filtro que mascara e-mails e telefones.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path

from PIL import Image, ImageOps

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_TELEFONE = re.compile(r"(?<!\d)(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[-\s]?\d{4}(?!\d)")


def normalizar_contato(contato: str) -> str:
    c = contato.strip().lower()
    return c if "@" in c else re.sub(r"\D", "", c)


def hash_contato(contato: str, salt: str) -> str:
    return hmac.new(salt.encode(), normalizar_contato(contato).encode(), hashlib.sha256).hexdigest()


def mascarar_contato(contato: str) -> str:
    c = contato.strip()
    if "@" in c:
        usuario, _, dominio = c.partition("@")
        return f"{usuario[:1]}***@{dominio}"
    digitos = re.sub(r"\D", "", c)
    return f"***{digitos[-2:]}" if len(digitos) >= 2 else "***"


def sanitizar(texto: str) -> str:
    """Rede de segurança para logs: nenhum e-mail ou telefone sai em claro."""
    texto = RE_EMAIL.sub(lambda m: mascarar_contato(m.group(0)), texto)
    return RE_TELEFONE.sub("[telefone]", texto)


def arredondar_coord(valor: float, casas: int = 3) -> float:
    """~100 m de precisão: suficiente para auditoria, sem rastrear a pessoa."""
    return round(valor, casas)


def gravar_foto_sem_metadados(origem: Path, destino: Path) -> None:
    """Regrava a imagem (corrigindo a rotação) sem EXIF/GPS."""
    with Image.open(origem) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        destino.parent.mkdir(parents=True, exist_ok=True)
        img.save(destino, format="JPEG", quality=92)


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 16), b""):
            h.update(bloco)
    return h.hexdigest()
