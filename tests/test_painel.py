"""Painel de revisão humana: decisões, transições válidas, auditoria e ausência de dado pessoal."""
import pytest
from fastapi.testclient import TestClient

from conftest import P1, P2, criar_relato
from rua_acesa_rpa.painel.app import criar_app


@pytest.fixture
def painel(ctx):
    criar_relato(ctx.cfg, "C1", pos=P1, contato="maria@example.com")
    criar_relato(ctx.cfg, "C2", pos=P2)
    ctx.robo.executar("processar")
    cliente = TestClient(criar_app(ctx.cfg, ctx.repo))
    sols = {s["poste_placa"]: s["id"] for s in ctx.repo.solicitacoes()}
    return cliente, ctx, sols


def test_pagina_lista_a_fila(painel):
    cliente, ctx, _ = painel
    html = cliente.get("/").text
    assert "RA-" in html and "IP0000001" in html and "Aprovar e enviar" in html


def test_aprovar_envia_registra_auditoria_e_notifica(painel):
    cliente, ctx, sols = painel
    r = cliente.post(f"/solicitacoes/{sols['IP0000001']}/aprovar", data={"revisor": "Ana"}, follow_redirects=False)
    assert r.status_code == 303 and "aprovada" in r.headers["location"]
    sol = ctx.repo.solicitacao(sols["IP0000001"])
    assert sol["status"] == "enviada" and sol["revisado_por"] == "Ana"
    assert any(e["etapa"] == "revisao" for e in ctx.repo.eventos())
    assert any("enviada à Prefeitura" in n["mensagem"] for n in ctx.repo.notificacoes())


def test_rejeitar_exige_motivo(painel):
    cliente, ctx, sols = painel
    r = cliente.post(f"/solicitacoes/{sols['IP0000002']}/rejeitar", data={"revisor": "Ana"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert ctx.repo.solicitacao(sols["IP0000002"])["status"] == "aguardando_revisao"
    cliente.post(f"/solicitacoes/{sols['IP0000002']}/rejeitar", data={"revisor": "Ana", "motivo": "foto sem poste"})
    assert ctx.repo.solicitacao(sols["IP0000002"])["status"] == "rejeitada"


def test_transicao_invalida_retorna_409(painel):
    cliente, _, sols = painel
    r = cliente.post(f"/api/solicitacoes/{sols['IP0000001']}/resolver", json={"revisor": "Ana"})
    assert r.status_code == 409


def test_resolver_alimenta_indicador_de_tempo_de_reparo(painel):
    cliente, _, sols = painel
    sid = sols["IP0000001"]
    assert cliente.post(f"/api/solicitacoes/{sid}/aprovar", json={"revisor": "Ana"}).status_code == 200
    assert cliente.post(f"/api/solicitacoes/{sid}/resolver", json={"revisor": "Ana"}).json()["status"] == "resolvida"
    ind = cliente.get("/api/indicadores").json()
    assert ind["solicitacoes_resolvidas"] == 1 and ind["tempo_medio_relato_reparo_h"] is not None


def test_api_nao_expoe_contato(painel):
    cliente, _, _ = painel
    texto = cliente.get("/api/fila").text
    assert "contato_hash" not in texto and "m***@" not in texto and "maria" not in texto


def test_foto_servida_e_path_traversal_bloqueado(painel):
    cliente, _, _ = painel
    assert cliente.get("/fotos/C1").headers["content-type"] == "image/jpeg"
    assert cliente.get("/fotos/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert cliente.get("/fotos/NAO-EXISTE").status_code == 404
