"""Fluxo de ponta a ponta: cenários de sucesso, de decisão e de falha do robô."""
import json

from PIL import Image

from conftest import P1, P2, P3, P4, criar_relato


def _status(repo, rid):
    return repo.relato(rid)["status"]


def _executar(ctx, **kw):
    return ctx.robo.executar("processar", **kw)


# ================================================================ sucesso
def test_lote_completo_sucesso(ctx):
    cfg, repo = ctx.cfg, ctx.repo
    ctx.visao.vereditos = {"C2": "nao_confirmado", "C3": "inconclusivo_dia"}
    criar_relato(cfg, "C1", pos=P1, contato="maria@example.com")
    criar_relato(cfg, "C2", pos=P2, contato="+55 11 91234-5678")
    criar_relato(cfg, "C3", pos=P3)
    criar_relato(cfg, "C4", pos=P1, offset_m=-4)                      # mesmo poste do C1
    criar_relato(cfg, "B1", origem="robo", pos=P4, lux=2.0)           # só sensor

    r = _executar(ctx)

    assert r.status == "concluida" and r.lidos == 5 and r.falhas_inesperadas == 0
    assert (r.confirmados, r.nao_confirmados, r.inconclusivos, r.leituras_robo) == (2, 1, 1, 1)
    assert (r.solicitacoes_novas, r.solicitacoes_reforcadas) == (3, 1)
    assert _status(repo, "C2") == "arquivado"
    sols = {s["poste_placa"]: s for s in repo.solicitacoes()}
    assert sols["IP0000001"]["qtd_relatos"] == 2 and sols["IP0000001"]["evidencia"] == "confirmada"
    assert sols["IP0000003"]["evidencia"] == "inconclusiva"
    assert sols["IP0000004"]["evidencia"] == "sensor"
    assert all(s["status"] == "aguardando_revisao" and s["protocolo"].startswith("RA-") for s in sols.values())
    assert "IP0000001" in sols["IP0000001"]["texto"]
    # arquivos: entrada vazia, tudo em processados/<run_id>/
    assert not list(cfg.pasta_entrada.glob("*.json"))
    assert len(list((cfg.pasta_processados / r.run_id).glob("*.json"))) == 5
    # exports para o mapa e para o pipeline de dados
    geo = json.loads((cfg.pasta_saida / "pontos_escuros.geojson").read_text())
    assert len(geo["features"]) == 3
    assert (cfg.pasta_saida / "solicitacoes.csv").read_text().count("\n") == 4
    # outbox: confirmado (C1) e não confirmado (C2) têm contato
    assert len(repo.notificacoes()) == 2


def test_prioridade_maior_quando_relatos_se_acumulam(ctx):
    criar_relato(ctx.cfg, "C1", pos=P1)
    _executar(ctx)
    antes = ctx.repo.solicitacoes()[0]["prioridade_score"]
    criar_relato(ctx.cfg, "C2", pos=P1, offset_m=2)
    criar_relato(ctx.cfg, "B1", origem="robo", pos=P1, lux=1.0)
    _executar(ctx)
    depois = ctx.repo.solicitacoes()[0]
    assert depois["prioridade_score"] == antes + 6 + 15 and depois["corroborado_robo"] == 1


# ================================================================ decisão / idempotência
def test_rodar_de_novo_nao_duplica(ctx):
    criar_relato(ctx.cfg, "C1", pos=P1)
    _executar(ctx)
    criar_relato(ctx.cfg, "C1", pos=P1)          # mesmo id reenviado
    r = _executar(ctx)
    assert r.duplicados == 1 and r.solicitacoes_novas == 0
    assert len(ctx.repo.solicitacoes()) == 1 and len(ctx.repo.todos_relatos()) == 1
    assert list((ctx.cfg.pasta_processados / r.run_id / "duplicados").glob("*.duplicado.txt"))


def test_mesma_foto_com_outro_id_e_duplicada(ctx):
    criar_relato(ctx.cfg, "C1", pos=P1)
    arq = criar_relato(ctx.cfg, "C2", pos=P1)
    (ctx.cfg.pasta_entrada / "C2.jpg").write_bytes((ctx.cfg.pasta_entrada / "C1.jpg").read_bytes())
    r = _executar(ctx)
    assert r.duplicados == 1 and ctx.repo.relato("C2") is None and arq.exists() is False


def test_robo_adequado_depois_do_relato_indica_reparo(ctx):
    criar_relato(ctx.cfg, "C1", pos=P1, minutos=60)
    _executar(ctx)
    criar_relato(ctx.cfg, "B1", origem="robo", pos=P1, lux=40.0, minutos=5)
    _executar(ctx)
    sol = ctx.repo.solicitacoes()[0]
    assert sol["indicio_reparo"] == 1 and _status(ctx.repo, "B1") == "vinculado"


def test_robo_sem_solicitacao_aberta_e_arquivado_e_divergencia_logada(ctx):
    criar_relato(ctx.cfg, "B1", origem="robo", pos=P2, lux=9.0, classificacao="adequado")
    _executar(ctx)
    rel = ctx.repo.relato("B1")
    assert rel["status"] == "arquivado" and rel["classificacao_rpa"] == "fraco"
    assert any(e["nivel"] == "WARN" and "vale a do RPA" in e["mensagem"] for e in ctx.repo.eventos())


def test_foto_recusada_pela_visao(ctx):
    ctx.visao.vereditos = {"C1": "http415"}
    criar_relato(ctx.cfg, "C1")
    r = _executar(ctx)
    assert r.rejeitados_visao == 1 and _status(ctx.repo, "C1") == "rejeitado_visao"
    assert not ctx.repo.solicitacoes()


# ================================================================ falhas e resiliência
def test_visao_fora_fica_pendente_e_e_reprocessada(ctx):
    ctx.visao.fora = True
    for i in range(4):
        criar_relato(ctx.cfg, f"C{i}", pos=P1, offset_m=i)
    r = _executar(ctx)
    assert r.status == "concluida" and r.pendentes_visao == 4
    assert all(_status(ctx.repo, f"C{i}") == "pendente_visao" for i in range(4))
    # health falhou => circuito abre na 1ª falha: 3 tentativas, os outros nem chamam
    assert len(ctx.visao.chamadas) == 3
    assert not ctx.repo.solicitacoes()

    ctx.visao.fora = False
    r2 = ctx.robo.executar("reprocessar")
    assert r2.reprocessados_ok == 4 and r2.pendentes_visao == 0
    assert ctx.repo.solicitacoes()[0]["qtd_relatos"] == 4


def test_open_meteo_e_geosampa_fora_nao_param_o_robo(ctx):
    ctx.clima.fora = True
    ctx.wfs.fora = True
    criar_relato(ctx.cfg, "C1", pos=P1)
    r = _executar(ctx)
    sol = ctx.repo.solicitacoes()[0]
    assert r.status == "concluida" and sol["poste_fonte"] == "csv" and sol["prioridade_score"] == 40
    assert "clima indisponível" in sol["prioridade_motivos"]
    assert len(r.avisos) == 2  # um aviso por integração, não um por relato


def test_falha_inesperada_isolada_no_item(ctx, monkeypatch):
    original = ctx.robo._vincular

    def explode(rel, evidencia, resumo):
        if rel["id"] == "C2":
            raise RuntimeError("disco cheio (simulado)")
        return original(rel, evidencia, resumo)

    monkeypatch.setattr(ctx.robo, "_vincular", explode)
    for rid in ("C1", "C2", "C3"):
        criar_relato(ctx.cfg, rid, pos=P1 if rid != "C3" else P2)
    r = _executar(ctx)
    assert r.status == "concluida_com_falhas" and r.falhas_inesperadas == 1
    assert ctx.repo.relato("C2") is None                          # desfeito: o reenvio será aceito
    nota = next((ctx.cfg.pasta_erros / r.run_id).glob("C2.erro.txt")).read_text()
    assert "disco cheio" in nota
    assert {s["poste_placa"] for s in ctx.repo.solicitacoes()} == {"IP0000001", "IP0000002"}
    assert ctx.repo.execucoes(1)[0]["status"] == "concluida_com_falhas"


def test_invalidos_vao_para_erros_com_motivo(ctx):
    (ctx.cfg.pasta_entrada / "X1.json").write_text("{quebrado", encoding="utf-8")
    criar_relato(ctx.cfg, "X2", pos=(-22.9, -43.2))
    r = _executar(ctx)
    pasta = ctx.cfg.pasta_erros / r.run_id
    assert r.invalidos == 2 and (pasta / "X2.jpg").exists()
    assert "JSON inválido" in (pasta / "X1.erro.txt").read_text()
    assert "fora do município" in (pasta / "X2.erro.txt").read_text()


def test_lote_limitado_deixa_restante_para_proxima(ctx):
    ctx.robo.cfg = ctx.cfg.com(max_lote=2)
    for i in range(3):
        criar_relato(ctx.cfg, f"C{i}", pos=P1, offset_m=i)
    r = _executar(ctx)
    assert r.lidos == 2 and r.restantes_na_fila == 1


# ================================================================ LGPD e auditoria
def test_contato_nunca_em_claro_e_foto_sem_exif(ctx):
    criar_relato(ctx.cfg, "C1", contato="maria.silva@example.com", descricao="me liga 11 91234-5678")
    exif = Image.Exif()
    exif[0x010F] = "Celular"
    Image.open(ctx.cfg.pasta_entrada / "C1.jpg").save(ctx.cfg.pasta_entrada / "C1.jpg", exif=exif)
    _executar(ctx)
    rel = ctx.repo.relato("C1")
    assert rel["contato_mascarado"] == "m***@example.com" and len(rel["contato_hash"]) == 64
    assert "91234" not in rel["descricao"]
    textos = [p.read_text() for p in ctx.cfg.pasta_logs.glob("*.jsonl")]
    textos += [p.read_text() for p in ctx.cfg.pasta_saida.iterdir()]
    assert not any("maria.silva" in t or "91234" in t for t in textos)
    assert not Image.open(ctx.cfg.pasta_fotos / "C1.jpg").getexif()


def test_log_jsonl_tem_campos_de_auditoria(ctx):
    criar_relato(ctx.cfg, "C1")
    r = _executar(ctx)
    linhas = [json.loads(x) for p in ctx.cfg.pasta_logs.glob("*.jsonl") for x in p.read_text().splitlines()]
    assert {"ts", "run_id", "nivel", "etapa", "mensagem", "relato_id"} <= set(linhas[0])
    etapas = [x["etapa"] for x in linhas if x["run_id"] == r.run_id]
    assert etapas[0] == "inicio" and etapas[-1] == "fim"
    assert {"recebido", "visao", "poste", "solicitacao", "exportacao"} <= set(etapas)
