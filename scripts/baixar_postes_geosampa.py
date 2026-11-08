"""Baixa um recorte do cadastro oficial de iluminação pública (GeoSampa, WFS) para dados/.

O robô consulta o WFS ao vivo para cada relato; este recorte é o plano B offline
(WFS fora do ar) e a base para montar o lote de demonstração com postes reais.

    python scripts/baixar_postes_geosampa.py            # regiões padrão
    python scripts/baixar_postes_geosampa.py --raio 500
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from rua_acesa_rpa.config import Config  # noqa: E402
from rua_acesa_rpa.geo import caixa_ao_redor  # noqa: E402
from rua_acesa_rpa.postes import CAMADA  # noqa: E402

# centro, uma região central e duas periféricas (ODS 10: comparar centro x periferia)
REGIOES = {
    "paulista": (-23.5613, -46.6565),
    "capao_redondo": (-23.6685, -46.7795),
    "cidade_tiradentes": (-23.5826, -46.4090),
}


def baixar(wfs: str, lat: float, lon: float, raio_m: float) -> list[dict]:
    lat_min, lon_min, lat_max, lon_max = caixa_ao_redor(lat, lon, raio_m)
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": CAMADA,
              "outputFormat": "application/json", "srsName": "EPSG:4326", "count": "10000",
              "bbox": f"{lat_min},{lon_min},{lat_max},{lon_max},urn:ogc:def:crs:EPSG::4326"}
    r = requests.get(wfs, params=params, timeout=60)
    r.raise_for_status()
    postes = {}
    for f in r.json()["features"]:
        p = f["properties"]
        placa = (p.get("cd_placa") or "").strip() or f"ID{p['cd_identificador_iluminacao_publica']}"
        lon_, lat_ = f["geometry"]["coordinates"][:2]
        postes.setdefault(placa, {"placa": placa, "latitude": round(lat_, 7), "longitude": round(lon_, 7),
                                  "endereco": (p.get("tx_endereco") or "").strip(),
                                  "tipo": (p.get("dc_tipo_iluminacao_publica") or "").strip(),
                                  "dt_carga": (p.get("dt_carga") or "").rstrip("Z")})
    return list(postes.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raio", type=float, default=350, help="meia-aresta do recorte por região, em metros")
    args = ap.parse_args()
    cfg = Config.carregar(RAIZ)
    linhas = []
    for nome, (lat, lon) in REGIOES.items():
        postes = baixar(cfg.geosampa_wfs_url, lat, lon, args.raio)
        for p in postes:
            p["regiao"] = nome
        linhas.extend(postes)
        print(f"{nome:<18} {len(postes):>5} postes")
    cfg.postes_csv.parent.mkdir(parents=True, exist_ok=True)
    with cfg.postes_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["placa", "latitude", "longitude", "endereco", "tipo", "dt_carga", "regiao"])
        w.writeheader()
        w.writerows(linhas)
    print(f"{len(linhas)} postes -> {cfg.postes_csv.relative_to(RAIZ)}  (fonte: GeoSampa/SMUL-ILUME, camada {CAMADA})")


if __name__ == "__main__":
    main()
