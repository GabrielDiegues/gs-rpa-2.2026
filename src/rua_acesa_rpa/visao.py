"""Cliente da API de visão (YOLO) do Rua Acesa: POST /detect e GET /health.

Resiliência:
- retry com backoff exponencial para falhas transitórias (conexão, timeout, HTTP 5xx);
- erros definitivos da foto (HTTP 413/415/422) não são repetidos;
- circuit breaker: após N relatos seguidos sem resposta, o lote para de chamar a
  visão e os relatos restantes ficam "pendente_visao" (reprocessados depois).
"""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Callable

import requests
from pydantic import ValidationError

from rua_acesa_rpa.modelos import ResultadoVisao


class VisaoIndisponivel(Exception):
    """A visão não respondeu (ou respondeu fora do contrato). O relato fica pendente."""


class FotoRejeitada(Exception):
    """A visão recusou a foto (tipo/tamanho/decodificação). Não adianta tentar de novo."""


class ClienteVisao:
    def __init__(self, url: str, timeout_s: float = 20.0, tentativas: int = 3, backoff_s: float = 1.0,
                 limite_circuito: int = 3, sessao: requests.Session | None = None,
                 dormir: Callable[[float], None] = time.sleep,
                 ao_tentar_novamente: Callable[[int, str], None] | None = None):
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.tentativas = max(1, tentativas)
        self.backoff_s = backoff_s
        self.limite_circuito = max(1, limite_circuito)
        self.sessao = sessao or requests.Session()
        self.dormir = dormir
        self.ao_tentar_novamente = ao_tentar_novamente
        self.falhas_seguidas = 0
        self.chamadas = 0

    @property
    def circuito_aberto(self) -> bool:
        return self.falhas_seguidas >= self.limite_circuito

    def saude(self) -> dict | None:
        try:
            r = self.sessao.get(f"{self.url}/health", timeout=min(self.timeout_s, 5))
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            return None

    def detectar(self, foto: Path) -> ResultadoVisao:
        if self.circuito_aberto:
            raise VisaoIndisponivel(f"circuito aberto após {self.falhas_seguidas} falhas seguidas")
        conteudo = foto.read_bytes()
        mime = mimetypes.guess_type(foto.name)[0] or "image/jpeg"
        ultimo_erro = "sem resposta"
        for tentativa in range(1, self.tentativas + 1):
            self.chamadas += 1
            try:
                r = self.sessao.post(f"{self.url}/detect", files={"file": (foto.name, conteudo, mime)},
                                     timeout=self.timeout_s)
                if r.status_code in (413, 415, 422):
                    self.falhas_seguidas = 0  # a API está no ar; o problema é a foto
                    raise FotoRejeitada(f"HTTP {r.status_code}: {_detalhe(r)}")
                if r.status_code >= 500:
                    raise _Transitorio(f"HTTP {r.status_code}: {_detalhe(r)}")
                r.raise_for_status()
                resultado = ResultadoVisao.model_validate(r.json())
                self.falhas_seguidas = 0
                return resultado
            except FotoRejeitada:
                raise
            except requests.Timeout:
                ultimo_erro = f"tempo esgotado ({self.timeout_s:.0f}s)"
            except requests.ConnectionError:
                ultimo_erro = f"sem conexão com {self.url}"
            except _Transitorio as e:
                ultimo_erro = str(e)
            except (requests.RequestException, ValueError, ValidationError) as e:
                # 4xx inesperado ou resposta fora do contrato: não é transitório, não repete
                ultimo_erro = f"resposta inválida da visão ({type(e).__name__})"
                break
            if tentativa < self.tentativas:
                espera = self.backoff_s * 2 ** (tentativa - 1)
                if self.ao_tentar_novamente:
                    self.ao_tentar_novamente(tentativa, f"{_curto(ultimo_erro)}; nova tentativa em {espera:.1f}s")
                self.dormir(espera)
        self.falhas_seguidas += 1
        raise VisaoIndisponivel(_curto(ultimo_erro))


class _Transitorio(Exception):
    pass


def _detalhe(r: requests.Response) -> str:
    try:
        return str(r.json().get("detail", r.text))[:200]
    except ValueError:
        return r.text[:200]


def _curto(msg: str) -> str:
    return msg if len(msg) <= 160 else msg[:157] + "..."
