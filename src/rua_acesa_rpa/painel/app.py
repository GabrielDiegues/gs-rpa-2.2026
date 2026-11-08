"""Painel de revisão humana do Rua Acesa (IA sugere, pessoa decide).

O robô deixa cada solicitação em "aguardando_revisao". Aqui um(a) revisor(a) vê a
foto, o veredito da IA, a leitura do robô, os motivos da prioridade e o texto
pronto, e decide: aprovar e enviar à Prefeitura, rejeitar (com motivo) ou, depois,
marcar como resolvida. Toda decisão vira evento de auditoria com nome e horário.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from rua_acesa_rpa.auditoria import Auditoria
from rua_acesa_rpa.config import Config
from rua_acesa_rpa.exportar import exportar_tudo, geojson_pontos, indicadores
from rua_acesa_rpa.lgpd import sanitizar
from rua_acesa_rpa.modelos import StatusSolicitacao
from rua_acesa_rpa.repositorio import Repositorio, agora_iso

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

TRANSICOES = {
    "aprovar": (StatusSolicitacao.AGUARDANDO_REVISAO, StatusSolicitacao.ENVIADA),
    "rejeitar": (StatusSolicitacao.AGUARDANDO_REVISAO, StatusSolicitacao.REJEITADA),
    "resolver": (StatusSolicitacao.ENVIADA, StatusSolicitacao.RESOLVIDA),
}
MSG_CIDADAO = {
    "aprovar": "A solicitação {protocolo} foi enviada à Prefeitura (SP156). Obrigado por relatar!",
    "resolver": "O poste da solicitação {protocolo} foi religado. Obrigado por ajudar a deixar a rua acesa!",
}


def _detalhar(repo: Repositorio, s: dict) -> dict:
    d = dict(s)
    d["motivos"] = json.loads(s["prioridade_motivos"] or "[]")
    d["clima"] = json.loads(s["clima_json"]) if s["clima_json"] else None
    d["relatos"] = repo.relatos_da_solicitacao(s["id"])
    return d


def criar_app(cfg: Config | None = None, repo: Repositorio | None = None) -> FastAPI:
    cfg = cfg or Config.carregar()
    repo = repo or Repositorio(cfg.banco)
    aud = Auditoria("painel", cfg.pasta_logs, repo)
    app = FastAPI(title="Rua Acesa — Painel de revisão", version="1.0.0",
                  description="Fila priorizada gerada pelo robô de RPA. A IA sugere; a pessoa decide.")
    app.state.repo = repo

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, msg: str | None = None, erro: str | None = None):
        fila = [_detalhar(repo, s) for s in repo.solicitacoes([StatusSolicitacao.AGUARDANDO_REVISAO])]
        enviadas = [_detalhar(repo, s) for s in repo.solicitacoes([StatusSolicitacao.ENVIADA])]
        encerradas = repo.solicitacoes([StatusSolicitacao.REJEITADA, StatusSolicitacao.RESOLVIDA])
        return TEMPLATES.TemplateResponse(request, "index.html", {
            "fila": fila, "enviadas": enviadas, "encerradas": encerradas[:20],
            "ind": indicadores(repo), "execucoes": repo.execucoes(8), "eventos": repo.eventos(limite=40),
            "msg": msg, "erro": erro,
        })

    @app.get("/fotos/{relato_id}")
    def foto(relato_id: str):
        rel = repo.relato(relato_id)
        if not rel or not rel["foto_arquivo"]:
            raise HTTPException(404, "foto não disponível (removida pela política de retenção ou inexistente)")
        caminho = (cfg.pasta_fotos / rel["foto_arquivo"]).resolve()
        if cfg.pasta_fotos.resolve() not in caminho.parents or not caminho.is_file():
            raise HTTPException(404, "foto não disponível")
        return FileResponse(caminho, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})

    def _decidir(sol_id: int, acao: str, revisor: str, motivo: str = "") -> dict:
        revisor = sanitizar(revisor.strip())[:60]
        motivo = sanitizar(motivo.strip())[:300]
        if not revisor:
            raise HTTPException(422, "informe o nome de quem está revisando")
        if acao == "rejeitar" and not motivo:
            raise HTTPException(422, "informe o motivo da rejeição")
        sol = repo.solicitacao(sol_id)
        if not sol:
            raise HTTPException(404, "solicitação não encontrada")
        origem, destino = TRANSICOES[acao]
        if sol["status"] != origem:
            raise HTTPException(409, f"{sol['protocolo']} está '{sol['status']}'; ação '{acao}' não se aplica")
        dados = {"status": destino, "revisado_por": revisor, "revisado_em": agora_iso()}
        if motivo:
            dados["motivo_revisao"] = motivo
        if acao == "resolver":
            dados["resolvido_em"] = agora_iso()
        repo.atualizar_solicitacao(sol_id, **dados)
        aud.registrar("revisao", f"{sol['protocolo']}: {origem} -> {destino} por {revisor}"
                                 + (f" (motivo: {motivo})" if motivo else ""), solicitacao_id=sol_id)
        if acao in MSG_CIDADAO:
            for rel in repo.relatos_da_solicitacao(sol_id):
                if rel["contato_hash"]:
                    repo.inserir_notificacao(rel["id"], rel["contato_hash"],
                                             MSG_CIDADAO[acao].format(protocolo=sol["protocolo"]))
        exportar_tudo(repo, cfg.pasta_saida)
        return repo.solicitacao(sol_id)

    def _form_ou_redirect(sol_id: int, acao: str, revisor: str, motivo: str = ""):
        try:
            sol = _decidir(sol_id, acao, revisor, motivo)
        except HTTPException as e:
            return RedirectResponse(f"/?erro={quote(str(e.detail))}#fila", status_code=303)
        verbo = {"aprovar": "aprovada e enviada", "rejeitar": "rejeitada", "resolver": "marcada como resolvida"}
        return RedirectResponse(f"/?msg={quote(sol['protocolo'] + ' ' + verbo[acao])}", status_code=303)

    @app.post("/solicitacoes/{sol_id}/aprovar")
    def aprovar(sol_id: int, revisor: str = Form("")):
        return _form_ou_redirect(sol_id, "aprovar", revisor)

    @app.post("/solicitacoes/{sol_id}/rejeitar")
    def rejeitar(sol_id: int, revisor: str = Form(""), motivo: str = Form("")):
        return _form_ou_redirect(sol_id, "rejeitar", revisor, motivo)

    @app.post("/solicitacoes/{sol_id}/resolver")
    def resolver(sol_id: int, revisor: str = Form("")):
        return _form_ou_redirect(sol_id, "resolver", revisor)

    # ------------------------------------------------------------------ API JSON (integração)
    @app.get("/api/fila")
    def api_fila():
        return [_detalhar(repo, s) | {"relatos": [_relato_publico(r) for r in repo.relatos_da_solicitacao(s["id"])]}
                for s in repo.solicitacoes([StatusSolicitacao.AGUARDANDO_REVISAO])]

    @app.get("/api/solicitacoes/{sol_id}")
    def api_solicitacao(sol_id: int):
        s = repo.solicitacao(sol_id)
        if not s:
            raise HTTPException(404, "solicitação não encontrada")
        d = _detalhar(repo, s)
        d["relatos"] = [_relato_publico(r) for r in d["relatos"]]
        d["eventos"] = repo.eventos(solicitacao_id=sol_id)
        return d

    @app.post("/api/solicitacoes/{sol_id}/{acao}")
    def api_decidir(sol_id: int, acao: str, payload: dict):
        if acao not in TRANSICOES:
            raise HTTPException(404, "ação inválida")
        return _decidir(sol_id, acao, str(payload.get("revisor", "")), str(payload.get("motivo", "")))

    @app.get("/api/pontos")
    def api_pontos():
        return geojson_pontos(repo)

    @app.get("/api/indicadores")
    def api_indicadores():
        return indicadores(repo)

    @app.get("/api/execucoes")
    def api_execucoes():
        return repo.execucoes(20)

    @app.get("/health")
    def health():
        return {"status": "ok", "banco": cfg.banco.name}

    return app


def _relato_publico(r: dict) -> dict:
    """Sem hash nem máscara de contato: a API do painel não expõe dado pessoal."""
    campos = ("id", "origem", "criado_em", "veredito", "motivo", "cena", "confianca_apagado", "leitura_lux",
              "classificacao_rpa", "classificacao_robo", "poste_placa", "distancia_poste_m", "status")
    return {k: r[k] for k in campos} | {"tem_foto": bool(r["foto_arquivo"]), "tem_contato": bool(r["contato_hash"])}
