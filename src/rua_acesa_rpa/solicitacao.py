"""Redação da solicitação para a Prefeitura (SP156 · Iluminação pública).

O texto padrão sai de um template determinístico (sempre disponível). Se LLM_URL
estiver configurada (componente de GenAI do Rua Acesa), o robô pede uma redação
mais natural e, em qualquer falha, volta para o template — a LLM nunca bloqueia o fluxo.
Em ambos os casos a solicitação só é enviada depois da aprovação humana no painel.
"""
from __future__ import annotations

from datetime import datetime

import requests

SERVICO_SP156 = "Iluminação pública — lâmpada apagada (reparo)"

_EVIDENCIA_TXT = {
    "confirmada": "foto analisada pela IA de visão confirmou poste apagado",
    "sensor": "medição do robô de inspeção indicou iluminação abaixo do mínimo (sem foto)",
    "inconclusiva": "foto não permitiu confirmação automática; requer análise do revisor",
}


def protocolo(sol_id: int, quando: datetime) -> str:
    return f"RA-{quando:%Y}-{sol_id:06d}"


def _fmt(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromisoformat(ts).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return ts


def redigir_template(sol: dict, relatos: list[dict]) -> str:
    cidadaos = [r for r in relatos if r["origem"] == "cidadao"]
    robos = [r for r in relatos if r["origem"] == "robo"]
    datas = sorted(r["criado_em"] for r in relatos)
    local = (f"poste de placa {sol['poste_placa']} ({sol.get('poste_tipo') or 'tipo não informado'}), "
             f"{sol.get('poste_endereco') or 'endereço não informado'}"
             if sol.get("poste_placa") else "ponto sem poste cadastrado no GeoSampa num raio próximo")
    linhas = [
        f"Serviço: {SERVICO_SP156}",
        f"Protocolo Rua Acesa: {sol.get('protocolo') or '—'}",
        f"Local: {local}. Coordenadas: {sol['latitude']:.5f}, {sol['longitude']:.5f}.",
        f"Relatos: {len(cidadaos)} de cidadão(s) e {len(robos)} leitura(s) do robô de inspeção, "
        f"entre {_fmt(datas[0] if datas else None)} e {_fmt(datas[-1] if datas else None)}.",
        f"Evidência: {_EVIDENCIA_TXT.get(sol['evidencia'], sol['evidencia'])}.",
    ]
    conf = max((r["confianca_apagado"] or 0 for r in cidadaos), default=0)
    if conf:
        linhas.append(f"Confiança máxima da IA para 'poste apagado': {conf:.0%}.")
    if robos:
        lux = min(r["leitura_lux"] for r in robos if r["leitura_lux"] is not None)
        linhas.append(f"Menor luminosidade medida pelo robô: {lux:.1f} lux.")
    linhas.append(f"Prioridade sugerida: {sol['prioridade_faixa'].upper()} ({sol['prioridade_score']}/100).")
    linhas.append("Solicitamos a verificação e o reparo da iluminação no local indicado.")
    return "\n".join(linhas)


def redigir(sol: dict, relatos: list[dict], llm_url: str = "", timeout_s: float = 30.0,
            sessao: requests.Session | None = None) -> tuple[str, str]:
    """Retorna (texto, origem) — origem = 'llm' ou 'template'."""
    base = redigir_template(sol, relatos)
    if not llm_url:
        return base, "template"
    try:
        r = (sessao or requests).post(f"{llm_url}/redigir-solicitacao",
                                      json={"rascunho": base, "servico": SERVICO_SP156}, timeout=timeout_s)
        r.raise_for_status()
        texto = str(r.json().get("texto", "")).strip()
        if 50 <= len(texto) <= 3000 and (not sol.get("poste_placa") or sol["poste_placa"] in texto):
            return texto, "llm"
    except (requests.RequestException, ValueError, AttributeError):
        pass
    return base, "template"
