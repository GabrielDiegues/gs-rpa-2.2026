"""Utilidades geográficas (distância em metros e limites do município de São Paulo)."""
from __future__ import annotations

import math

RAIO_TERRA_M = 6_371_000.0

# Retângulo envolvente do município de São Paulo (WGS84), com pequena folga.
SP_LAT_MIN, SP_LAT_MAX = -24.01, -23.35
SP_LON_MIN, SP_LON_MAX = -46.83, -46.36


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAIO_TERRA_M * math.asin(math.sqrt(a))


def dentro_de_sp(lat: float, lon: float) -> bool:
    return SP_LAT_MIN <= lat <= SP_LAT_MAX and SP_LON_MIN <= lon <= SP_LON_MAX


def caixa_ao_redor(lat: float, lon: float, raio_m: float) -> tuple[float, float, float, float]:
    """(lat_min, lon_min, lat_max, lon_max) de um quadrado com meia-aresta raio_m."""
    dlat = math.degrees(raio_m / RAIO_TERRA_M)
    dlon = math.degrees(raio_m / (RAIO_TERRA_M * math.cos(math.radians(lat))))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon
