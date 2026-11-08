"""CLI do robô Rua Acesa.

    python -m rua_acesa_rpa processar              # reprocessa pendentes + processa o lote de entrada/
    python -m rua_acesa_rpa reprocessar-pendentes  # só os relatos que aguardam a visão
    python -m rua_acesa_rpa agendar --intervalo 5  # roda 'processar' a cada N minutos (Ctrl+C para sair)
    python -m rua_acesa_rpa painel                 # painel de revisão humana (http://localhost:8001)
    python -m rua_acesa_rpa exportar               # regenera os arquivos de saida/
    python -m rua_acesa_rpa status                 # resumo do estado atual
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from rua_acesa_rpa.auditoria import configurar_console, logger
from rua_acesa_rpa.config import Config
from rua_acesa_rpa.exportar import exportar_tudo, indicadores
from rua_acesa_rpa.pipeline import Robo
from rua_acesa_rpa.repositorio import Repositorio


def _imprimir_resumo(resumo) -> None:
    d = resumo.como_dict()
    print("\n=== Resumo da execução", d["run_id"], "===")
    for chave in ("status", "lidos", "sucessos", "invalidos", "duplicados", "confirmados", "nao_confirmados",
                  "inconclusivos", "rejeitados_visao", "leituras_robo", "solicitacoes_novas",
                  "solicitacoes_reforcadas", "pendentes_visao", "reprocessados_ok", "falhas_inesperadas",
                  "restantes_na_fila", "fotos_removidas_lgpd"):
        print(f"  {chave:<24} {d[chave]}")
    for aviso in d["avisos"]:
        print(f"  AVISO: {aviso}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rua_acesa_rpa", description="Robô de automação do Rua Acesa")
    parser.add_argument("-v", "--verboso", action="store_true")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("processar", help="reprocessa pendentes e processa o lote de entrada/")
    p.add_argument("--sem-reprocessar", action="store_true", help="não tenta os pendentes da visão")
    sub.add_parser("reprocessar-pendentes", help="tenta de novo os relatos que aguardam a visão")
    a = sub.add_parser("agendar", help="executa 'processar' periodicamente")
    a.add_argument("--intervalo", type=float, default=5.0, help="minutos entre execuções (padrão 5)")
    pn = sub.add_parser("painel", help="painel web de revisão humana")
    pn.add_argument("--porta", type=int, default=None)
    pn.add_argument("--host", default="127.0.0.1")
    sub.add_parser("exportar", help="regenera os arquivos de saida/")
    sub.add_parser("status", help="indicadores e últimas execuções")
    args = parser.parse_args(argv)

    configurar_console(args.verboso)
    cfg = Config.carregar()

    if args.comando == "painel":
        import uvicorn

        from rua_acesa_rpa.painel.app import criar_app
        uvicorn.run(criar_app(cfg), host=args.host, port=args.porta or cfg.painel_porta)
        return 0

    if args.comando == "exportar":
        repo = Repositorio(cfg.banco)
        for c in exportar_tudo(repo, cfg.pasta_saida):
            print(c.relative_to(cfg.raiz))
        return 0

    if args.comando == "status":
        repo = Repositorio(cfg.banco)
        print(json.dumps(indicadores(repo), ensure_ascii=False, indent=2))
        for e in repo.execucoes(5):
            print(f"{e['inicio']}  {e['tipo']:<12} {e['status']:<22} lidos={e['resumo'].get('lidos', 0)} "
                  f"falhas={e['resumo'].get('falhas_inesperadas', 0)}")
        return 0

    robo = Robo(cfg)
    if args.comando == "processar":
        resumo = robo.executar("processar", reprocessar=not args.sem_reprocessar)
        _imprimir_resumo(resumo)
        return 0 if resumo.status == "concluida" else 2
    if args.comando == "reprocessar-pendentes":
        resumo = robo.executar("reprocessar")
        _imprimir_resumo(resumo)
        return 0 if resumo.status == "concluida" else 2
    if args.comando == "agendar":
        logger.info("agendador: 'processar' a cada %.1f min (Ctrl+C para encerrar)", args.intervalo)
        try:
            while True:
                try:
                    _imprimir_resumo(Robo(cfg).executar("processar"))
                except Exception as e:  # noqa: BLE001 — o agendador sobrevive a uma execução ruim
                    logger.error("execução falhou: %s: %s", type(e).__name__, e)
                time.sleep(args.intervalo * 60)
        except KeyboardInterrupt:
            logger.info("agendador encerrado")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
