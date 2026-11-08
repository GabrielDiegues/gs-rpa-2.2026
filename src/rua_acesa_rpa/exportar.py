"""Exports em saida/ — o contrato com os outros componentes do Rua Acesa.

- pontos_escuros.geojson : solicitações abertas (mapa "onde a cidade está escura")
- fila_revisao.json      : fila priorizada aguardando revisão humana
- solicitacoes.csv       : todas as solicitações (tabela fato p/ Airflow → Databricks)
- relatos.csv            : relatos pseudonimizados (sem contato em claro, coord. 4 casas)
- indicadores.json       : indicadores de impacto da ficha técnica

Escrita atômica (arquivo temporário + rename): quem lê nunca pega arquivo pela metade.
Formato detalhado em docs/contrato_dados.md.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from rua_acesa_rpa.modelos import STATUS_ABERTOS, StatusSolicitacao
from rua_acesa_rpa.repositorio import Repositorio, agora_iso

CAMPOS_SOLICITACAO = ["protocolo", "status", "evidencia", "prioridade_score", "prioridade_faixa",
                      "qtd_relatos", "qtd_relatos_cidadao", "corroborado_robo", "indicio_reparo",
                      "poste_placa", "poste_endereco", "poste_tipo", "poste_fonte", "latitude", "longitude",
                      "primeiro_relato_em", "criado_em", "atualizado_em", "revisado_em", "resolvido_em"]
CAMPOS_RELATO = ["id", "origem", "criado_em", "recebido_em", "latitude", "longitude", "status", "veredito",
                 "cena", "confianca_apagado", "classificacao_rpa", "leitura_lux", "poste_placa",
                 "distancia_poste_m", "protocolo", "contato_hash"]


def _gravar_atomico(caminho: Path, conteudo: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(conteudo, encoding="utf-8")
    tmp.replace(caminho)


def _csv(linhas: list[dict], campos: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=campos, extrasaction="ignore")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue()


def _horas_entre(inicio: str | None, fim: str | None) -> float | None:
    if not inicio or not fim:
        return None
    return (datetime.fromisoformat(fim) - datetime.fromisoformat(inicio)).total_seconds() / 3600


def indicadores(repo: Repositorio) -> dict:
    sols = repo.solicitacoes()
    resolvidas = [s for s in sols if s["status"] == StatusSolicitacao.RESOLVIDA]
    tempos = [h for s in resolvidas if (h := _horas_entre(s["primeiro_relato_em"], s["resolvido_em"])) is not None]
    abertas = [s for s in sols if s["status"] in STATUS_ABERTOS]
    cid_analisados = repo.contagem("SELECT COUNT(*) FROM relatos WHERE origem='cidadao' AND veredito IS NOT NULL")
    cid_confirmados = repo.contagem("SELECT COUNT(*) FROM relatos WHERE origem='cidadao' AND veredito='confirmado'")
    agrupados = sum(max(s["qtd_relatos"] - 1, 0) for s in sols)
    duplicados = repo.contagem("SELECT COUNT(*) FROM eventos WHERE etapa='duplicado'")
    return {
        "gerado_em": agora_iso(),
        "tempo_medio_relato_reparo_h": round(sum(tempos) / len(tempos), 1) if tempos else None,
        "solicitacoes_resolvidas": len(resolvidas),
        "pontos_escuros_ativos": sum(1 for s in abertas if s["evidencia"] in ("confirmada", "sensor")),
        "solicitacoes_abertas": len(abertas),
        "aguardando_revisao": sum(1 for s in abertas if s["status"] == StatusSolicitacao.AGUARDANDO_REVISAO),
        "enviadas_prefeitura": sum(1 for s in abertas if s["status"] == StatusSolicitacao.ENVIADA),
        "relatos_confirmados_ia_pct": round(100 * cid_confirmados / cid_analisados, 1) if cid_analisados else None,
        "relatos_agrupados_no_mesmo_poste": agrupados,
        "reenvios_duplicados_descartados": duplicados,
        "duplicados_evitados": agrupados + duplicados,
        "por_faixa": {f: sum(1 for s in abertas if s["prioridade_faixa"] == f) for f in ("alta", "media", "baixa")},
    }


def geojson_pontos(repo: Repositorio) -> dict:
    feats = []
    for s in repo.solicitacoes([*STATUS_ABERTOS]):
        props = {k: s[k] for k in ("protocolo", "status", "evidencia", "prioridade_score", "prioridade_faixa",
                                   "qtd_relatos", "poste_placa", "poste_endereco", "poste_tipo",
                                   "indicio_reparo", "atualizado_em")}
        feats.append({"type": "Feature", "id": s["protocolo"],
                      "geometry": {"type": "Point", "coordinates": [round(s["longitude"], 6), round(s["latitude"], 6)]},
                      "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def exportar_tudo(repo: Repositorio, pasta: Path) -> list[Path]:
    sols = repo.solicitacoes()
    protocolo_por_id = {s["id"]: s["protocolo"] for s in sols}
    relatos = []
    for r in repo.todos_relatos():
        r = dict(r)
        r["protocolo"] = protocolo_por_id.get(r["solicitacao_id"])
        r["latitude"], r["longitude"] = round(r["latitude"], 4), round(r["longitude"], 4)
        relatos.append(r)
    fila = [{k: s[k] for k in ("protocolo", "prioridade_score", "prioridade_faixa", "evidencia", "qtd_relatos",
                               "poste_placa", "poste_endereco", "latitude", "longitude", "criado_em", "texto")}
            | {"motivos_prioridade": json.loads(s["prioridade_motivos"])}
            for s in repo.solicitacoes([StatusSolicitacao.AGUARDANDO_REVISAO])]

    saidas = {
        "pontos_escuros.geojson": json.dumps(geojson_pontos(repo), ensure_ascii=False, indent=1),
        "fila_revisao.json": json.dumps({"gerado_em": agora_iso(), "itens": fila}, ensure_ascii=False, indent=1),
        "solicitacoes.csv": _csv(sols, CAMPOS_SOLICITACAO),
        "relatos.csv": _csv(relatos, CAMPOS_RELATO),
        "indicadores.json": json.dumps(indicadores(repo), ensure_ascii=False, indent=1),
    }
    caminhos = []
    for nome, conteudo in saidas.items():
        _gravar_atomico(pasta / nome, conteudo)
        caminhos.append(pasta / nome)
    return caminhos
