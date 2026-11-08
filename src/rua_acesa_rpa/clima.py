"""Condição climática noturna no local do relato (Open-Meteo, sem chave).

Usada pela regra de prioridade: rua escura + noite chuvosa/encoberta = mais risco
para quem anda a pé. Janela analisada: 6 h passadas + 12 h seguintes, só horas
noturnas (is_day = 0). Falha na API não interrompe o fluxo: a prioridade é
calculada sem o fator clima e o fato fica registrado no log.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Callable

import requests

LIMIAR_CHUVA_MM = 0.2
LIMIAR_NUVENS_PCT = 80.0


@dataclass(frozen=True)
class CondicaoClima:
    disponivel: bool
    chuva_noturna: bool = False
    precipitacao_noturna_mm: float = 0.0
    nebulosidade_noturna_pct: float | None = None
    horas_noturnas: int = 0
    detalhe: str = ""

    @property
    def encoberto(self) -> bool:
        return self.nebulosidade_noturna_pct is not None and self.nebulosidade_noturna_pct > LIMIAR_NUVENS_PCT

    def como_dict(self) -> dict:
        return {**asdict(self), "encoberto": self.encoberto}


INDISPONIVEL = CondicaoClima(disponivel=False, detalhe="clima não consultado")


class ClienteClima:
    def __init__(self, url: str, timeout_s: float = 10.0, tentativas: int = 2,
                 sessao: requests.Session | None = None, dormir: Callable[[float], None] = time.sleep):
        self.url = url
        self.timeout_s = timeout_s
        self.tentativas = max(1, tentativas)
        self.sessao = sessao or requests.Session()
        self.dormir = dormir
        self._cache: dict[tuple[float, float], CondicaoClima] = {}

    def consultar(self, lat: float, lon: float) -> CondicaoClima:
        chave = (round(lat, 2), round(lon, 2))  # ~1 km: relatos vizinhos compartilham a consulta
        if chave in self._cache:
            return self._cache[chave]
        params = {"latitude": chave[0], "longitude": chave[1], "hourly": "precipitation,cloud_cover,is_day",
                  "timezone": "America/Sao_Paulo", "past_hours": 6, "forecast_hours": 12}
        erro = ""
        for tentativa in range(1, self.tentativas + 1):
            try:
                r = self.sessao.get(self.url, params=params, timeout=self.timeout_s)
                r.raise_for_status()
                cond = self._interpretar(r.json())
                self._cache[chave] = cond
                return cond
            except (requests.RequestException, ValueError, KeyError, TypeError) as e:
                erro = f"{type(e).__name__}"
                if tentativa < self.tentativas:
                    self.dormir(1.0)
        cond = CondicaoClima(disponivel=False, detalhe=f"Open-Meteo indisponível ({erro})")
        self._cache[chave] = cond  # não insiste no mesmo lote
        return cond

    @staticmethod
    def _interpretar(dados: dict) -> CondicaoClima:
        h = dados["hourly"]
        noturnas = [(p or 0.0, c) for p, c, d in zip(h["precipitation"], h["cloud_cover"], h["is_day"]) if d == 0]
        if not noturnas:
            return CondicaoClima(disponivel=True, detalhe="nenhuma hora noturna na janela")
        precip = round(sum(p for p, _ in noturnas), 1)
        nuvens = [c for _, c in noturnas if c is not None]
        neb = round(sum(nuvens) / len(nuvens), 1) if nuvens else None
        chuva = any(p >= LIMIAR_CHUVA_MM for p, _ in noturnas)
        return CondicaoClima(disponivel=True, chuva_noturna=chuva, precipitacao_noturna_mm=precip,
                             nebulosidade_noturna_pct=neb, horas_noturnas=len(noturnas),
                             detalhe=f"{len(noturnas)} h noturnas, {precip} mm, nuvens {neb}%")
