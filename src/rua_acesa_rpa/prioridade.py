"""Regra de prioridade da solicitação (funções puras, testadas em tests/test_prioridade.py).

Pontuação (0–100):
  base   confirmada pelo YOLO = 40 | só sensor do robô = 25 | inconclusiva = 20
  +6     por relato de cidadão além do primeiro (máx. +30)
  +15    chuva prevista/ocorrida em horário noturno (Open-Meteo)
  +10    céu encoberto (> 80% de nuvens) à noite
  +15    robô de inspeção corroborou "escuro" (quando a base não veio só dele)
  +1     por dia em aberto (máx. +10)
Faixas: alta >= 70 | média >= 45 | baixa < 45.
"""
from __future__ import annotations

from dataclasses import dataclass

from rua_acesa_rpa.clima import CondicaoClima
from rua_acesa_rpa.modelos import Evidencia

BASE = {Evidencia.CONFIRMADA: 40, Evidencia.SENSOR: 25, Evidencia.INCONCLUSIVA: 20}
LIMIAR_ALTA = 70
LIMIAR_MEDIA = 45


@dataclass(frozen=True)
class Prioridade:
    score: int
    faixa: str
    motivos: list[str]


def faixa_de(score: int) -> str:
    if score >= LIMIAR_ALTA:
        return "alta"
    if score >= LIMIAR_MEDIA:
        return "media"
    return "baixa"


def calcular(evidencia: Evidencia, qtd_relatos_cidadao: int, corroborado_robo: bool,
             clima: CondicaoClima | None, dias_aberto: int) -> Prioridade:
    score = BASE[evidencia]
    motivos = [f"evidência {evidencia.value} (+{score})"]

    extras = min(max(qtd_relatos_cidadao - 1, 0), 5)
    if extras:
        score += 6 * extras
        motivos.append(f"{extras} relato(s) adicional(is) de cidadãos (+{6 * extras})")

    if clima is None or not clima.disponivel:
        motivos.append("clima indisponível (fator ignorado)")
    else:
        if clima.chuva_noturna:
            score += 15
            motivos.append(f"chuva noturna {clima.precipitacao_noturna_mm} mm (+15)")
        if clima.encoberto:
            score += 10
            motivos.append(f"céu encoberto à noite {clima.nebulosidade_noturna_pct:.0f}% (+10)")

    if corroborado_robo and evidencia != Evidencia.SENSOR:
        score += 15
        motivos.append("robô de inspeção mediu 'escuro' no local (+15)")

    dias = min(max(dias_aberto, 0), 10)
    if dias:
        score += dias
        motivos.append(f"{dias} dia(s) em aberto (+{dias})")

    score = min(score, 100)
    return Prioridade(score=score, faixa=faixa_de(score), motivos=motivos)


def classificar_luminosidade(lux: float, limiar_escuro: float, limiar_fraco: float) -> str:
    """Reconfere a leitura do LDR do robô (lux) com limiares configuráveis (ABNT NBR 5101)."""
    if lux < limiar_escuro:
        return "escuro"
    if lux < limiar_fraco:
        return "fraco"
    return "adequado"
