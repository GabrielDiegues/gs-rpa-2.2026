"""Fixtures: dublês das APIs externas (visão, GeoSampa, Open-Meteo) e fábrica de relatos.

Os dublês respeitam os contratos reais:
- visão: mesmo JSON de app/schemas.py do repositório de visão;
- GeoSampa: GeoJSON do WFS (coordenadas [lon, lat], placa repetida por luminária);
- Open-Meteo: listas paralelas em "hourly".
"""
from __future__ import annotations

import csv
import json
import random
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from PIL import Image

from rua_acesa_rpa.clima import ClienteClima
from rua_acesa_rpa.config import Config
from rua_acesa_rpa.pipeline import Robo
from rua_acesa_rpa.postes import LocalizadorPostes
from rua_acesa_rpa.repositorio import Repositorio, agora
from rua_acesa_rpa.visao import ClienteVisao

# (placa, lat, lon, endereço, tipo) — coordenadas reais aproximadas
POSTES = [
    ("IP0000001", -23.56100, -46.65600, "AVENIDA PAULISTA", "LED"),
    ("IP0000002", -23.56250, -46.65850, "ALAMEDA SANTOS", "LED"),
    ("IP0000003", -23.67000, -46.78000, "RUA DOS MUTIRANTES", "LED"),
    ("IP0000004", -23.58260, -46.40900, "AVENIDA SOUZA RAMOS", "LED"),
]
P1, P2, P3, P4 = [(p[1], p[2]) for p in POSTES]


class Resp:
    def __init__(self, status: int, dados=None, texto: str = ""):
        self.status_code = status
        self._dados = dados
        self.text = texto or json.dumps(dados)

    def json(self):
        if self._dados is None:
            raise ValueError("sem JSON")
        return self._dados

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def resposta_visao(veredito: str, cena: str = "noite", conf: float = 0.91) -> dict:
    classe = {"confirmado": "poste_apagado", "nao_confirmado": "poste_aceso"}.get(veredito)
    if veredito == "inconclusivo" and cena == "dia":
        classe = "poste_apagado"
    det = [{"classe": classe, "confianca": conf, "bbox": [10, 10, 50, 90]}] if classe else []
    return {"veredito": veredito, "motivo": f"teste: {veredito}", "cena": cena, "brilho_medio": 60.0,
            "deteccoes": det, "largura": 640, "altura": 640, "modelo": "best.pt", "tempo_ms": 7.0}


class SessaoVisao:
    """vereditos: id do relato -> confirmado | nao_confirmado | inconclusivo | inconclusivo_dia |
    http415 | http500 | lixo. Padrão: confirmado."""

    def __init__(self, vereditos: dict | None = None):
        self.vereditos = vereditos or {}
        self.fora = False
        self.timeouts_restantes = 0
        self.chamadas: list[str] = []

    def get(self, url, timeout=None, **_):
        if self.fora:
            raise requests.ConnectionError("recusada")
        return Resp(200, {"status": "ok", "modelo": "best.pt", "classes": ["poste_aceso", "poste_apagado"]})

    def post(self, url, files=None, timeout=None, **_):
        rid = Path(files["file"][0]).stem
        self.chamadas.append(rid)
        if self.fora:
            raise requests.ConnectionError("recusada")
        if self.timeouts_restantes:
            self.timeouts_restantes -= 1
            raise requests.Timeout("lento")
        v = self.vereditos.get(rid, "confirmado")
        if v == "http415":
            return Resp(415, {"detail": "Tipo não suportado"})
        if v == "http500":
            return Resp(500, {"detail": "erro interno"})
        if v == "lixo":
            return Resp(200, {"inesperado": True})
        if v == "inconclusivo_dia":
            return Resp(200, resposta_visao("inconclusivo", cena="dia"))
        return Resp(200, resposta_visao(v))


class SessaoWFS:
    def __init__(self, postes=POSTES):
        self.postes = postes
        self.fora = False
        self.chamadas = 0

    def get(self, url, params=None, timeout=None, **_):
        self.chamadas += 1
        if self.fora:
            raise requests.ConnectionError("WFS fora")
        lat_min, lon_min, lat_max, lon_max = (float(x) for x in params["bbox"].split(",")[:4])
        feats = []
        for i, (placa, lat, lon, end, tipo) in enumerate(self.postes):
            if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                for _ in range(2):  # o cadastro repete a placa por luminária
                    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                  "properties": {"cd_identificador_iluminacao_publica": i, "cd_placa": placa,
                                                 "tx_endereco": end, "dc_tipo_iluminacao_publica": tipo}})
        return Resp(200, {"type": "FeatureCollection", "features": feats})


class SessaoClima:
    def __init__(self, chuva: bool = True, nuvens: int = 100):
        self.chuva, self.nuvens = chuva, nuvens
        self.fora = False
        self.chamadas = 0

    def get(self, url, params=None, timeout=None, **_):
        self.chamadas += 1
        if self.fora:
            raise requests.ConnectionError("Open-Meteo fora")
        n = 18
        return Resp(200, {"hourly": {"time": [f"t{i}" for i in range(n)],
                                     "precipitation": [0.5 if self.chuva else 0.0] * n,
                                     "cloud_cover": [self.nuvens] * n,
                                     "is_day": [0] * 6 + [1] * 6 + [0] * 6}})


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config(raiz=tmp_path, salt_lgpd="salt-de-teste", visao_backoff_s=0.0, visao_url="http://visao.teste",
               geosampa_wfs_url="http://wfs.teste", clima_url="http://clima.teste")
    c.criar_pastas()
    with c.postes_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["placa", "latitude", "longitude", "endereco", "tipo"])
        w.writerows(POSTES)
    return c


@pytest.fixture
def ctx(cfg: Config):
    repo = Repositorio(cfg.banco)
    sv, sw, sc = SessaoVisao(), SessaoWFS(), SessaoClima()
    dormidas: list[float] = []
    visao = ClienteVisao(cfg.visao_url, tentativas=3, backoff_s=0.0, limite_circuito=3, sessao=sv,
                         dormir=dormidas.append)
    postes = LocalizadorPostes(cfg.geosampa_wfs_url, repo, cfg.postes_csv, sessao=sw)
    clima = ClienteClima(cfg.clima_url, sessao=sc, dormir=lambda s: None)
    robo = Robo(cfg, repo=repo, visao=visao, postes=postes, clima=clima)
    yield SimpleNamespace(cfg=cfg, repo=repo, robo=robo, visao=sv, wfs=sw, clima=sc, dormidas=dormidas)
    repo.fechar()


def foto_unica(caminho: Path, seed: int | None = None) -> Path:
    """JPEG pequeno e único (hash diferente a cada chamada)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (64, 48), tuple(rnd.randrange(256) for _ in range(3)))
    img.putpixel((rnd.randrange(64), rnd.randrange(48)), (rnd.randrange(256), 0, 0))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img.save(caminho, "JPEG")
    return caminho


def criar_relato(cfg: Config, rid: str, origem: str = "cidadao", pos=P1, minutos: int = 30, *,
                 contato: str | None = None, lux: float | None = None, classificacao: str | None = None,
                 foto: bool = True, offset_m: float = 3.0, **extra) -> Path:
    lat = pos[0] + offset_m / 111_320
    dados = {"id": rid, "origem": origem, "criado_em": (agora() - timedelta(minutes=minutos)).isoformat(),
             "latitude": round(lat, 6), "longitude": pos[1]}
    if contato:
        dados["contato"] = contato
    if origem == "cidadao" and foto:
        foto_unica(cfg.pasta_entrada / f"{rid}.jpg")
        dados["foto"] = f"{rid}.jpg"
    if origem == "robo":
        dados["leitura"] = {"dispositivo_id": "vision-wheel-01", "luminosidade_lux": lux if lux is not None else 2.0}
        if classificacao:
            dados["leitura"]["classificacao"] = classificacao
    dados.update(extra)
    arq = cfg.pasta_entrada / f"{rid}.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return arq
