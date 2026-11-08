"""Associação do relato ao poste oficial mais próximo (cadastro de iluminação do GeoSampa).

Ordem de consulta (degrada com elegância):
1. WFS público do GeoSampa (camada geoportal:iluminacao_publica, ~663 mil pontos),
   consultado ao vivo só na vizinhança do relato; o resultado vai para o cache;
2. cache local (tabela postes_cache) — se o WFS estiver fora do ar;
3. recorte versionado dados/postes_geosampa.csv (scripts/baixar_postes_geosampa.py).
Sem poste dentro do raio, a deduplicação usa a distância entre relatos.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import requests

from rua_acesa_rpa.geo import caixa_ao_redor, haversine_m
from rua_acesa_rpa.repositorio import Repositorio

CAMADA = "geoportal:iluminacao_publica"


@dataclass(frozen=True)
class Poste:
    placa: str
    latitude: float
    longitude: float
    endereco: str | None = None
    tipo: str | None = None


@dataclass(frozen=True)
class ResultadoPoste:
    poste: Poste | None
    distancia_m: float | None
    fonte: str          # geosampa_wfs | cache | csv | nenhuma
    aviso: str | None = None


class LocalizadorPostes:
    def __init__(self, wfs_url: str, repo: Repositorio, csv_path: Path | None = None,
                 timeout_s: float = 10.0, sessao: requests.Session | None = None):
        self.wfs_url = wfs_url
        self.repo = repo
        self.csv_path = csv_path
        self.timeout_s = timeout_s
        self.sessao = sessao or requests.Session()
        self._csv: list[Poste] | None = None
        self.wfs_falhou = False  # depois de uma falha no lote, não insiste a cada relato

    # ------------------------------------------------------------------ WFS
    def _consultar_wfs(self, lat: float, lon: float, raio_m: float) -> list[Poste]:
        lat_min, lon_min, lat_max, lon_max = caixa_ao_redor(lat, lon, raio_m)
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": CAMADA,
            "outputFormat": "application/json", "srsName": "EPSG:4326", "count": "500",
            # WFS 2.0 + EPSG:4326 => ordem latitude, longitude
            "bbox": f"{lat_min},{lon_min},{lat_max},{lon_max},urn:ogc:def:crs:EPSG::4326",
        }
        r = self.sessao.get(self.wfs_url, params=params, timeout=self.timeout_s)
        r.raise_for_status()
        dados = r.json()
        postes: dict[str, Poste] = {}
        for f in dados.get("features", []):
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if geom.get("type") != "Point" or len(coords) < 2:
                continue
            props = f.get("properties") or {}
            placa = (props.get("cd_placa") or "").strip() or f"ID{props.get('cd_identificador_iluminacao_publica')}"
            # o cadastro repete a placa para cada luminária do mesmo poste: 1 poste por placa
            postes.setdefault(placa, Poste(placa=placa, longitude=float(coords[0]), latitude=float(coords[1]),
                                           endereco=(props.get("tx_endereco") or "").strip() or None,
                                           tipo=(props.get("dc_tipo_iluminacao_publica") or "").strip() or None))
        return list(postes.values())

    # ------------------------------------------------------------------ fallback
    def _carregar_csv(self) -> list[Poste]:
        if self._csv is None:
            self._csv = []
            if self.csv_path and self.csv_path.is_file():
                with self.csv_path.open(encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        try:
                            self._csv.append(Poste(placa=row["placa"], latitude=float(row["latitude"]),
                                                   longitude=float(row["longitude"]),
                                                   endereco=row.get("endereco") or None,
                                                   tipo=row.get("tipo") or None))
                        except (KeyError, ValueError):
                            continue
        return self._csv

    @staticmethod
    def _mais_proximo(postes: list[Poste], lat: float, lon: float, raio_m: float) -> tuple[Poste | None, float | None]:
        melhor, melhor_d = None, None
        for p in postes:
            d = haversine_m(lat, lon, p.latitude, p.longitude)
            if d <= raio_m and (melhor_d is None or d < melhor_d):
                melhor, melhor_d = p, d
        return melhor, (round(melhor_d, 1) if melhor_d is not None else None)

    # ------------------------------------------------------------------ API
    def localizar(self, lat: float, lon: float, raio_m: float) -> ResultadoPoste:
        aviso = None
        if not self.wfs_falhou:
            try:
                postes = self._consultar_wfs(lat, lon, raio_m)
                if postes:
                    self.repo.salvar_postes_cache([p.__dict__ for p in postes])
                poste, d = self._mais_proximo(postes, lat, lon, raio_m)
                return ResultadoPoste(poste, d, "geosampa_wfs" if poste else "nenhuma")
            except (requests.RequestException, ValueError) as e:
                self.wfs_falhou = True
                aviso = f"GeoSampa WFS indisponível ({type(e).__name__}); usando cache/recorte local"

        caixa = caixa_ao_redor(lat, lon, raio_m)
        cache = [Poste(placa=c["placa"], latitude=c["latitude"], longitude=c["longitude"],
                       endereco=c["endereco"], tipo=c["tipo"]) for c in self.repo.postes_cache_na_caixa(*caixa)]
        poste, d = self._mais_proximo(cache, lat, lon, raio_m)
        if poste:
            return ResultadoPoste(poste, d, "cache", aviso)
        poste, d = self._mais_proximo(self._carregar_csv(), lat, lon, raio_m)
        if poste:
            return ResultadoPoste(poste, d, "csv", aviso)
        return ResultadoPoste(None, None, "nenhuma", aviso)
