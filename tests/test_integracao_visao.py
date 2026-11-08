"""Integração REAL com a API de visão (repositório gs-computer-vision-2.2026).

Roda só se a API estiver no ar:  pytest -m integracao
(suba antes, no repositório de visão:  uvicorn app.main:app --port 8000)
"""
import os
from pathlib import Path

import pytest

from rua_acesa_rpa.visao import ClienteVisao

AMOSTRAS = Path(__file__).resolve().parents[1] / "assets" / "amostras"
URL = os.getenv("VISAO_URL", "http://localhost:8000")

pytestmark = pytest.mark.integracao


@pytest.fixture(scope="module")
def cliente():
    c = ClienteVisao(URL, timeout_s=30, tentativas=1)
    if not c.saude():
        pytest.skip(f"API de visão fora do ar em {URL}")
    return c


@pytest.mark.parametrize("foto, veredito, cena", [
    ("noite_sintetica_apagado_2.jpg", "confirmado", "noite"),
    ("noite_aceso_2.jpg", "nao_confirmado", "noite"),
    ("dia_apagado_1.jpg", "inconclusivo", "dia"),
])
def test_veredito_real(cliente, foto, veredito, cena):
    r = cliente.detectar(AMOSTRAS / foto)
    assert (r.veredito, r.cena) == (veredito, cena)
