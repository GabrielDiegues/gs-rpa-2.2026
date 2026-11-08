"""Deduplicação: um poste apagado = uma solicitação aberta, não importa quantos relatos.

Com poste oficial associado, a chave é a placa do GeoSampa. Sem poste no raio, o
relato é agrupado com a solicitação aberta (também sem poste) mais próxima dentro
de RAIO_DEDUP_M.
"""
from __future__ import annotations

from rua_acesa_rpa.geo import haversine_m
from rua_acesa_rpa.postes import Poste
from rua_acesa_rpa.repositorio import Repositorio


def solicitacao_aberta_para(repo: Repositorio, poste: Poste | None, lat: float, lon: float,
                            raio_dedup_m: float) -> dict | None:
    if poste is not None:
        return repo.solicitacao_aberta_por_placa(poste.placa)
    candidatas = [(haversine_m(lat, lon, s["latitude"], s["longitude"]), s)
                  for s in repo.solicitacoes_abertas_sem_poste()]
    candidatas = [c for c in candidatas if c[0] <= raio_dedup_m]
    return min(candidatas, key=lambda c: c[0])[1] if candidatas else None
