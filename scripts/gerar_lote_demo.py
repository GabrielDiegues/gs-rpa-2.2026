"""Monta em entrada/ um lote de relatos de demonstração que cobre todos os cenários do robô.

Os relatos ficam a poucos metros de postes REAIS do cadastro GeoSampa (dados/postes_geosampa.csv)
e usam as fotos de teste do componente de visão (assets/amostras/, datasets CC BY 4.0).
Contatos são fictícios (domínio example.com / número de exemplo).

    python scripts/gerar_lote_demo.py            # lote 1: primeira noite
    python scripts/gerar_lote_demo.py --lote 2   # lote 2: reenvio, robô confirma reparo, novo relato
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageOps

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from rua_acesa_rpa.repositorio import agora  # noqa: E402

AMOSTRAS = RAIZ / "assets" / "amostras"
ENTRADA = RAIZ / "entrada"
CSV = RAIZ / "dados" / "postes_geosampa.csv"


def carregar_postes() -> list[dict]:
    if not CSV.exists():
        sys.exit("dados/postes_geosampa.csv não existe: rode antes scripts/baixar_postes_geosampa.py")
    with CSV.open(encoding="utf-8") as f:
        return sorted(csv.DictReader(f), key=lambda r: r["placa"])


def escolher(postes: list[dict], regiao: str, endereco_contem: str = "", pular: int = 0) -> dict:
    cand = [p for p in postes if p["regiao"] == regiao and endereco_contem in p["endereco"]]
    return cand[pular]


def deslocar(p: dict, norte_m: float, leste_m: float) -> tuple[float, float]:
    lat = float(p["latitude"]) + norte_m / 111_320
    lon = float(p["longitude"]) + leste_m / (111_320 * math.cos(math.radians(float(p["latitude"]))))
    return round(lat, 6), round(lon, 6)


def gravar(relato: dict, foto_origem: str | None = None, foto_nome: str | None = None) -> None:
    ENTRADA.mkdir(exist_ok=True)
    if foto_origem:
        nome = foto_nome or f"{relato['id']}.jpg"
        shutil.copy2(AMOSTRAS / foto_origem, ENTRADA / nome)
        relato["foto"] = nome
    (ENTRADA / f"{relato['id']}.json").write_text(json.dumps(relato, ensure_ascii=False, indent=2), encoding="utf-8")


def ts(min_atras: int) -> str:
    return (agora() - timedelta(minutes=min_atras)).isoformat(timespec="seconds")


def cidadao(rid, pos, min_atras, descricao, contato=None):
    r = {"id": rid, "origem": "cidadao", "criado_em": ts(min_atras), "latitude": pos[0], "longitude": pos[1],
         "descricao": descricao}
    if contato:
        r["contato"] = contato
    return r


def robo(rid, pos, min_atras, lux, classificacao):
    return {"id": rid, "origem": "robo", "criado_em": ts(min_atras), "latitude": pos[0], "longitude": pos[1],
            "leitura": {"dispositivo_id": "vision-wheel-01", "luminosidade_lux": lux,
                        "classificacao": classificacao}}


def lote1(postes: list[dict]) -> None:
    p1 = escolher(postes, "paulista", "AVENIDA PAULISTA")
    p2 = escolher(postes, "paulista", "ALAMEDA SANTOS")
    p3 = escolher(postes, "capao_redondo")
    p4 = escolher(postes, "cidade_tiradentes")
    p5 = escolher(postes, "capao_redondo", pular=40)
    p6 = escolher(postes, "cidade_tiradentes", pular=60)
    p7 = escolher(postes, "paulista", pular=200)

    gravar(cidadao("R-1001", deslocar(p1, 3, 2), 95, "Poste apagado em frente ao ponto de ônibus",
                   "maria.exemplo@example.com"), "noite_sintetica_apagado_2.jpg")
    gravar(cidadao("R-1002", deslocar(p1, -3, 2), 80, "Rua escura, poste não acende"),
           "noite_sintetica_apagado_1.jpg")
    gravar(robo("R-1003", deslocar(p1, 1, -1), 60, 2.1, "escuro"))
    gravar(cidadao("R-1004", deslocar(p2, 5, 0), 75, "Acho que o poste está fraco", "+55 11 91234-5678"),
           "noite_aceso_2.jpg")
    gravar(cidadao("R-1005", deslocar(p3, 4, 4), 70, "Poste apagado faz uma semana",
                   "joao.exemplo@example.com"), "dia_apagado_1.jpg")
    gravar(cidadao("R-1006", deslocar(p4, -5, 3), 65, "Trecho todo escuro perto da escola"),
           "noite_sintetica_apagado_3.jpg")
    gravar(robo("R-1007", deslocar(p5, 2, 2), 50, 3.4, "escuro"))
    gravar(robo("R-1008", deslocar(p6, 1, 1), 45, 9.0, "adequado"))       # RPA reclassifica: fraco
    gravar(robo("R-1009", deslocar(p7, 2, -1), 40, 32.0, "adequado"))
    # --- cenários de falha / exceção ---
    (ENTRADA / "R-1010.json").write_text('{"id": "R-1010", "origem": "cidadao", "latitude": -23.56,', encoding="utf-8")
    r = cidadao("R-1011", deslocar(p1, 10, 10), 30, "Foto não anexada")
    r["foto"] = "R-1011.jpg"  # arquivo não existe
    (ENTRADA / "R-1011.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    gravar(cidadao("R-1012", (-22.9068, -43.1729), 25, "Relato fora de São Paulo"), "noite_sintetica_apagado_1.jpg",
           "R-1012.jpg")
    gravar(cidadao("R-1013", deslocar(p1, 3, 2), 20, "Reenviando o mesmo relato"), "noite_sintetica_apagado_2.jpg",
           "R-1013.jpg")                                                    # mesma foto do R-1001
    bad = robo("R-1014", deslocar(p5, 1, 1), 15, 3.0, "escuro")
    bad["leitura"]["luminosidade_lux"] = -4                                 # leitura impossível
    gravar(bad)


def lote2(postes: list[dict]) -> None:
    p1 = escolher(postes, "paulista", "AVENIDA PAULISTA")
    p4 = escolher(postes, "cidade_tiradentes")
    gravar(cidadao("R-1001", deslocar(p1, 3, 2), 5, "Reenvio pelo app"), "noite_sintetica_apagado_2.jpg",
           "R-1001-reenvio.jpg")                                            # mesmo id => duplicado
    gravar(robo("R-2001", deslocar(p1, 2, 1), 4, 28.5, "adequado"))         # indício de reparo
    # outro morador fotografa o mesmo poste de outro ângulo (amostra espelhada)
    ENTRADA.mkdir(exist_ok=True)
    with Image.open(AMOSTRAS / "noite_sintetica_apagado_3.jpg") as img:
        ImageOps.mirror(img).save(ENTRADA / "R-2002.jpg", quality=90)
    r = cidadao("R-2002", deslocar(p4, 3, -4), 3, "Continua escuro aqui", "ana.exemplo@example.com")
    r["foto"] = "R-2002.jpg"
    (ENTRADA / "R-2002.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lote", type=int, choices=(1, 2), default=1)
    args = ap.parse_args()
    postes = carregar_postes()
    (lote1 if args.lote == 1 else lote2)(postes)
    print(f"lote {args.lote}: {len(list(ENTRADA.glob('*.json')))} relato(s) em entrada/")


if __name__ == "__main__":
    main()
