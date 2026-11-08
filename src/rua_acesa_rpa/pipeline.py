"""Orquestração do robô: processa o lote de relatos de ponta a ponta.

Para cada relato (estrutura de repetição sobre a coleção do lote):
  1 validar → 2 idempotência → 3 decisão por origem (visão YOLO | leitura LDR)
  → 4 poste oficial (GeoSampa) → 5 deduplicação → 6 clima → 7 prioridade
  → 8 texto da solicitação → 9 persistência + auditoria
Cada relato é isolado em try/except: um item com problema vai para erros/ com o
motivo e o lote continua. Nenhuma falha é silenciosa (log JSONL + evento no banco).
"""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from rua_acesa_rpa import lgpd
from rua_acesa_rpa.auditoria import Auditoria
from rua_acesa_rpa.clima import INDISPONIVEL, ClienteClima, CondicaoClima
from rua_acesa_rpa.config import Config
from rua_acesa_rpa.deduplicacao import solicitacao_aberta_para
from rua_acesa_rpa.entrada import listar_lote, mover_para
from rua_acesa_rpa.exportar import exportar_tudo
from rua_acesa_rpa.modelos import STATUS_ABERTOS, Evidencia, StatusRelato, StatusSolicitacao
from rua_acesa_rpa.postes import LocalizadorPostes
from rua_acesa_rpa.prioridade import calcular, classificar_luminosidade
from rua_acesa_rpa.repositorio import Repositorio, agora, agora_iso
from rua_acesa_rpa.solicitacao import protocolo, redigir
from rua_acesa_rpa.validacao import RelatoInvalido, validar_relato
from rua_acesa_rpa.visao import ClienteVisao, FotoRejeitada, VisaoIndisponivel

MSG_NAO_CONFIRMADO = ("Analisamos a foto do seu relato e o poste aparece aceso. Se a rua continuar escura, "
                      "envie uma nova foto à noite.")
MSG_FOTO_DIA = ("Sua foto foi tirada de dia, quando o poste fica desligado. Para confirmarmos o defeito, "
                "envie uma nova foto à noite.")
MSG_CONFIRMADO = "Seu relato foi confirmado e incluído na solicitação {protocolo}, que está em revisão."


@dataclass
class Resumo:
    run_id: str
    tipo: str
    inicio: str
    fim: str | None = None
    status: str = "em_andamento"
    lidos: int = 0
    invalidos: int = 0
    duplicados: int = 0
    confirmados: int = 0
    nao_confirmados: int = 0
    inconclusivos: int = 0
    rejeitados_visao: int = 0
    leituras_robo: int = 0
    solicitacoes_novas: int = 0
    solicitacoes_reforcadas: int = 0
    pendentes_visao: int = 0
    reprocessados_ok: int = 0
    falhas_inesperadas: int = 0
    restantes_na_fila: int = 0
    fotos_removidas_lgpd: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def sucessos(self) -> int:
        return (self.confirmados + self.nao_confirmados + self.inconclusivos + self.leituras_robo
                + self.duplicados)

    def como_dict(self) -> dict:
        return {**asdict(self), "sucessos": self.sucessos}

    def linha(self) -> str:
        return (f"lidos={self.lidos} sucessos={self.sucessos} invalidos={self.invalidos} "
                f"duplicados={self.duplicados} confirmados={self.confirmados} "
                f"nao_confirmados={self.nao_confirmados} inconclusivos={self.inconclusivos} "
                f"robo={self.leituras_robo} novas={self.solicitacoes_novas} "
                f"reforcadas={self.solicitacoes_reforcadas} pendentes_visao={self.pendentes_visao} "
                f"reprocessados={self.reprocessados_ok} falhas={self.falhas_inesperadas}")


class Robo:
    def __init__(self, cfg: Config, repo: Repositorio | None = None, visao: ClienteVisao | None = None,
                 postes: LocalizadorPostes | None = None, clima: ClienteClima | None = None):
        self.cfg = cfg
        self.repo = repo or Repositorio(cfg.banco)
        self.visao = visao or ClienteVisao(cfg.visao_url, cfg.visao_timeout_s, cfg.visao_tentativas,
                                           cfg.visao_backoff_s, cfg.visao_limite_circuito)
        self.postes = postes or LocalizadorPostes(cfg.geosampa_wfs_url, self.repo, cfg.postes_csv,
                                                  cfg.geosampa_timeout_s)
        self.clima = clima or ClienteClima(cfg.clima_url, cfg.clima_timeout_s)
        self.aud: Auditoria | None = None
        self._avisos_emitidos: set[str] = set()

    # ================================================================== execução
    def executar(self, tipo: str = "processar", reprocessar: bool = True) -> Resumo:
        run_id = f"{agora():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        resumo = Resumo(run_id=run_id, tipo=tipo, inicio=agora_iso())
        self.aud = Auditoria(run_id, self.cfg.pasta_logs, self.repo)
        # cada execução começa com o circuito "meio-aberto": a visão ganha nova chance
        self.visao.falhas_seguidas = 0
        self.postes.wfs_falhou = False
        self._avisos_emitidos = set()
        self.visao.ao_tentar_novamente = lambda n, msg: self.aud.registrar(
            "visao", f"tentativa {n} falhou: {msg}", "WARN")
        self.repo.iniciar_execucao(run_id, tipo)
        self.aud.registrar("inicio", f"execução '{tipo}' iniciada")
        try:
            self._checar_visao(resumo)
            if reprocessar or tipo == "reprocessar":
                self._reprocessar_pendentes(resumo)
            if tipo == "processar":
                self._processar_lote(resumo)
            self._atualizar_abertas()
            self._limpeza_lgpd(resumo)
            arquivos = exportar_tudo(self.repo, self.cfg.pasta_saida)
            self.aud.registrar("exportacao", f"{len(arquivos)} arquivo(s) atualizados em saida/")
            resumo.status = "concluida" if resumo.falhas_inesperadas == 0 else "concluida_com_falhas"
        except Exception as e:  # falha geral (ex.: banco inacessível) — registra e propaga
            resumo.status = "falhou"
            self.aud.registrar("fim", f"execução interrompida: {type(e).__name__}: {e}", "ERROR")
            raise
        finally:
            resumo.fim = agora_iso()
            resumo.avisos = sorted(self._avisos_emitidos)
            self.repo.finalizar_execucao(run_id, resumo.status, resumo.como_dict())
            self.aud.registrar("fim", f"{resumo.status}: {resumo.linha()}",
                               "INFO" if resumo.status == "concluida" else "WARN")
        return resumo

    def _avisar_uma_vez(self, etapa: str, msg: str) -> None:
        if msg not in self._avisos_emitidos:
            self._avisos_emitidos.add(msg)
            self.aud.registrar(etapa, msg, "WARN")

    def _checar_visao(self, resumo: Resumo) -> None:
        saude = self.visao.saude()
        if saude:
            self.aud.registrar("visao", f"API de visão no ar (modelo {saude.get('modelo')}, "
                                        f"classes {saude.get('classes')})")
        else:
            # mais uma falha abre o circuito: evita gastar o lote inteiro em tentativas
            self.visao.falhas_seguidas = max(self.visao.falhas_seguidas, self.visao.limite_circuito - 1)
            self._avisar_uma_vez("visao", f"API de visão não respondeu em {self.cfg.visao_url}/health; "
                                          "relatos de cidadão poderão ficar pendentes")

    # ================================================================== lote
    def _processar_lote(self, resumo: Resumo) -> None:
        arquivos, restantes = listar_lote(self.cfg.pasta_entrada, self.cfg.max_lote)
        resumo.restantes_na_fila = restantes
        if not arquivos:
            self.aud.registrar("lote", "nenhum relato novo em entrada/")
            return
        self.aud.registrar("lote", f"{len(arquivos)} relato(s) no lote"
                                   + (f"; {restantes} ficam para a próxima execução" if restantes else ""))
        destino_ok = self.cfg.pasta_processados / resumo.run_id
        destino_erro = self.cfg.pasta_erros / resumo.run_id
        for arq in arquivos:
            resumo.lidos += 1
            try:
                duplicado = self._processar_arquivo(arq, resumo)
                if duplicado:
                    mover_para(arq, destino_ok / "duplicados", duplicado, ".duplicado.txt")
                else:
                    mover_para(arq, destino_ok)
            except RelatoInvalido as e:
                resumo.invalidos += 1
                self.aud.registrar("validacao", f"{arq.name} rejeitado: {e}", "WARN")
                self._mover_seguro(arq, destino_erro, str(e))
            except Exception as e:  # noqa: BLE001 — isola o item; o lote continua
                resumo.falhas_inesperadas += 1
                self.aud.registrar("falha", f"{arq.name}: erro inesperado {type(e).__name__}: {e}", "ERROR")
                self._mover_seguro(arq, destino_erro, f"falha inesperada: {type(e).__name__}: {e}")

    def _mover_seguro(self, arq: Path, destino: Path, nota: str) -> None:
        try:
            if arq.exists():
                mover_para(arq, destino, nota)
        except OSError as e:
            self.aud.registrar("falha", f"não foi possível mover {arq.name} para erros/: {e}", "ERROR")

    def _processar_arquivo(self, arq: Path, resumo: Resumo) -> str | None:
        """Retorna uma nota se o relato for duplicado; None se foi tratado normalmente."""
        v = validar_relato(arq, max_foto_mb=self.cfg.max_foto_mb, max_idade_dias=self.cfg.max_idade_relato_dias)
        r = v.relato

        # 2. idempotência: mesmo id ou mesma foto já recebidos => não processa de novo
        existente = self.repo.relato(r.id)
        if existente:
            nota = f"relato {r.id} já recebido em {existente['recebido_em']} (status {existente['status']})"
            return self._duplicado(r.id, nota, resumo)
        sha = lgpd.sha256_arquivo(v.foto) if v.foto else None
        if sha and (mesmo := self.repo.relato_por_foto(sha)):
            return self._duplicado(r.id, f"mesma foto do relato {mesmo['id']}", resumo)

        foto_arquivo = None
        if v.foto:
            foto_arquivo = f"{r.id}.jpg"
            lgpd.gravar_foto_sem_metadados(v.foto, self.cfg.pasta_fotos / foto_arquivo)

        self.repo.inserir_relato({
            "id": r.id, "origem": r.origem, "criado_em": r.criado_em.isoformat(timespec="seconds"),
            "recebido_em": agora_iso(), "latitude": r.latitude, "longitude": r.longitude,
            "descricao": lgpd.sanitizar(r.descricao) if r.descricao else None,
            "foto_sha256": sha, "foto_arquivo": foto_arquivo,
            "contato_hash": lgpd.hash_contato(r.contato, self.cfg.salt_lgpd) if r.contato else None,
            "contato_mascarado": lgpd.mascarar_contato(r.contato) if r.contato else None,
            "dispositivo_id": r.leitura.dispositivo_id if r.leitura else None,
            "leitura_lux": r.leitura.luminosidade_lux if r.leitura else None,
            "classificacao_robo": r.leitura.classificacao if r.leitura else None,
            "status": StatusRelato.PENDENTE_VISAO if r.origem == "cidadao" else "recebido",
            "run_id": self.aud.run_id,
        })
        self.aud.registrar("recebido", f"relato de {r.origem} em ({lgpd.arredondar_coord(r.latitude)}, "
                                       f"{lgpd.arredondar_coord(r.longitude)})"
                                       + (" com contato (pseudonimizado)" if r.contato else ""), relato_id=r.id)
        try:
            self._avaliar(self.repo.relato(r.id), resumo)
        except Exception:
            self._desfazer_relato(r.id)
            raise
        return None

    def _desfazer_relato(self, relato_id: str) -> None:
        """Falha inesperada antes de vincular: apaga o registro para o reenvio corrigido ser aceito."""
        rel = self.repo.relato(relato_id)
        if rel and rel["solicitacao_id"] is None:
            if rel["foto_arquivo"]:
                (self.cfg.pasta_fotos / rel["foto_arquivo"]).unlink(missing_ok=True)
            self.repo.conn.execute("DELETE FROM relatos WHERE id = ?", (relato_id,))

    def _duplicado(self, relato_id: str, nota: str, resumo: Resumo) -> str:
        resumo.duplicados += 1
        self.aud.registrar("duplicado", nota, relato_id=relato_id)
        return nota

    # ================================================================== decisão
    def _avaliar(self, rel: dict, resumo: Resumo) -> None:
        if rel["origem"] == "cidadao":
            evidencia = self._avaliar_foto(rel, resumo)
        else:
            evidencia = self._avaliar_leitura(rel, resumo)
        if evidencia is not None:
            self._vincular(self.repo.relato(rel["id"]), evidencia, resumo)

    def _avaliar_foto(self, rel: dict, resumo: Resumo) -> Evidencia | None:
        rid = rel["id"]
        foto = self.cfg.pasta_fotos / (rel["foto_arquivo"] or "")
        if not rel["foto_arquivo"] or not foto.is_file():
            raise RuntimeError("foto do relato não está mais disponível em dados/fotos/")
        try:
            rv = self.visao.detectar(foto)
        except FotoRejeitada as e:
            resumo.rejeitados_visao += 1
            self.repo.atualizar_relato(rid, status=StatusRelato.REJEITADO_VISAO, motivo=str(e))
            self.aud.registrar("visao", f"foto recusada pela visão: {e}", "WARN", relato_id=rid)
            return None
        except VisaoIndisponivel as e:
            resumo.pendentes_visao += 1
            self.repo.atualizar_relato(rid, status=StatusRelato.PENDENTE_VISAO,
                                       tentativas_visao=rel["tentativas_visao"] + 1, motivo=str(e))
            self.aud.registrar("visao", f"visão indisponível ({e}); relato fica pendente para a próxima "
                                        "execução", "WARN", relato_id=rid)
            return None

        self.repo.atualizar_relato(rid, veredito=rv.veredito, motivo=rv.motivo, cena=rv.cena,
                                   confianca_apagado=rv.confianca_apagado,
                                   tentativas_visao=rel["tentativas_visao"] + 1)
        self.aud.registrar("visao", f"veredito={rv.veredito} cena={rv.cena} "
                                    f"conf_apagado={rv.confianca_apagado:.2f} ({rv.tempo_ms:.0f} ms) — {rv.motivo}",
                           relato_id=rid)
        if rv.veredito == "nao_confirmado":
            resumo.nao_confirmados += 1
            self.repo.atualizar_relato(rid, status=StatusRelato.ARQUIVADO)
            self._notificar(rel, MSG_NAO_CONFIRMADO)
            self.aud.registrar("decisao", "arquivado: IA viu apenas poste(s) aceso(s)", relato_id=rid)
            return None
        if rv.veredito == "confirmado":
            resumo.confirmados += 1
            return Evidencia.CONFIRMADA
        resumo.inconclusivos += 1
        if rv.cena == "dia":
            self._notificar(rel, MSG_FOTO_DIA)
        self.aud.registrar("decisao", "inconclusivo: vai para a fila de revisão humana com sinalização",
                           relato_id=rid)
        return Evidencia.INCONCLUSIVA

    def _avaliar_leitura(self, rel: dict, resumo: Resumo) -> Evidencia | None:
        rid = rel["id"]
        resumo.leituras_robo += 1
        cls = classificar_luminosidade(rel["leitura_lux"], self.cfg.ldr_limiar_escuro_lux,
                                       self.cfg.ldr_limiar_fraco_lux)
        self.repo.atualizar_relato(rid, classificacao_rpa=cls)
        if rel["classificacao_robo"] and rel["classificacao_robo"] != cls:
            self.aud.registrar("robo", f"robô classificou '{rel['classificacao_robo']}', limiares do RPA dão "
                                       f"'{cls}' ({rel['leitura_lux']:.1f} lux) — vale a do RPA", "WARN",
                               relato_id=rid)
        else:
            self.aud.registrar("robo", f"leitura {rel['leitura_lux']:.1f} lux => {cls}", relato_id=rid)
        if cls == "escuro":
            return Evidencia.SENSOR

        # adequado/fraco: só interessa se já existe solicitação aberta no poste
        loc = self.postes.localizar(rel["latitude"], rel["longitude"], self.cfg.raio_poste_m)
        if loc.aviso:
            self._avisar_uma_vez("poste", loc.aviso)
        sol = solicitacao_aberta_para(self.repo, loc.poste, rel["latitude"], rel["longitude"], self.cfg.raio_dedup_m)
        if sol is None:
            self.repo.atualizar_relato(rid, status=StatusRelato.ARQUIVADO,
                                       poste_placa=loc.poste.placa if loc.poste else None,
                                       distancia_poste_m=loc.distancia_m)
            self.aud.registrar("decisao", f"arquivado: iluminação {'fraca' if cls == 'fraco' else 'adequada'} e nenhuma solicitação aberta no local",
                               relato_id=rid)
            return None
        self.repo.atualizar_relato(rid, status=StatusRelato.VINCULADO, solicitacao_id=sol["id"],
                                   poste_placa=loc.poste.placa if loc.poste else None,
                                   distancia_poste_m=loc.distancia_m)
        self._recalcular(sol["id"])
        msg = ("indício de reparo: robô mediu iluminação adequada" if cls == "adequado"
               else "leitura 'fraco' anexada como evidência")
        self.aud.registrar("decisao", f"{msg} em {sol['protocolo']}", relato_id=rid, solicitacao_id=sol["id"])
        return None

    # ================================================================== poste, dedup, prioridade
    def _vincular(self, rel: dict, evidencia: Evidencia, resumo: Resumo) -> None:
        rid, lat, lon = rel["id"], rel["latitude"], rel["longitude"]
        loc = self.postes.localizar(lat, lon, self.cfg.raio_poste_m)
        if loc.aviso:
            self._avisar_uma_vez("poste", loc.aviso)
        if loc.poste:
            self.aud.registrar("poste", f"poste {loc.poste.placa} ({loc.poste.endereco or 's/ endereço'}, "
                                        f"{loc.poste.tipo or 's/ tipo'}) a {loc.distancia_m} m [{loc.fonte}]",
                               relato_id=rid)
        else:
            self.aud.registrar("poste", f"nenhum poste oficial em {self.cfg.raio_poste_m:.0f} m; deduplicação "
                                        "por distância", "WARN", relato_id=rid)
        clima = self.clima.consultar(lat, lon)
        if not clima.disponivel:
            self._avisar_uma_vez("clima", clima.detalhe or "clima indisponível")

        with self.repo.transacao():
            sol = solicitacao_aberta_para(self.repo, loc.poste, lat, lon, self.cfg.raio_dedup_m)
            if sol is None:
                p = loc.poste
                sol_id = self.repo.inserir_solicitacao({
                    "poste_placa": p.placa if p else None, "poste_endereco": p.endereco if p else None,
                    "poste_tipo": p.tipo if p else None, "poste_fonte": loc.fonte,
                    "latitude": p.latitude if p else lat, "longitude": p.longitude if p else lon,
                    "status": StatusSolicitacao.AGUARDANDO_REVISAO, "evidencia": evidencia,
                    "primeiro_relato_em": rel["criado_em"],
                })
                self.repo.atualizar_solicitacao(sol_id, protocolo=protocolo(sol_id, agora()))
                nova = True
            else:
                sol_id, nova = sol["id"], False
            self.repo.atualizar_relato(rid, status=StatusRelato.VINCULADO, solicitacao_id=sol_id,
                                       poste_placa=loc.poste.placa if loc.poste else None,
                                       distancia_poste_m=loc.distancia_m)
        if nova:
            resumo.solicitacoes_novas += 1
        else:
            resumo.solicitacoes_reforcadas += 1
        sol = self._recalcular(sol_id, clima)
        acao = "nova solicitação" if nova else "agrupado na solicitação existente (deduplicado)"
        self.aud.registrar("solicitacao", f"{acao} {sol['protocolo']} — prioridade {sol['prioridade_faixa']} "
                                          f"({sol['prioridade_score']}) com {sol['qtd_relatos']} relato(s)",
                           relato_id=rid, solicitacao_id=sol_id)
        if evidencia == Evidencia.CONFIRMADA:
            self._notificar(rel, MSG_CONFIRMADO.format(protocolo=sol["protocolo"]))

    def _recalcular(self, sol_id: int, clima: CondicaoClima | None = None, redigir_texto: bool = True) -> dict:
        sol = self.repo.solicitacao(sol_id)
        relatos = self.repo.relatos_da_solicitacao(sol_id)
        cid = [r for r in relatos if r["origem"] == "cidadao"]
        robos = [r for r in relatos if r["origem"] == "robo"]
        if any(r["veredito"] == "confirmado" for r in cid):
            evidencia = Evidencia.CONFIRMADA
        elif any(r["classificacao_rpa"] == "escuro" for r in robos):
            evidencia = Evidencia.SENSOR
        else:
            evidencia = Evidencia.INCONCLUSIVA
        corroborado = any(r["classificacao_rpa"] == "escuro" for r in robos)
        ultimo_cid = max((r["criado_em"] for r in cid), default="")
        ultimo_escuro = max((r["criado_em"] for r in robos if r["classificacao_rpa"] == "escuro"), default="")
        adequados = [r["criado_em"] for r in robos if r["classificacao_rpa"] == "adequado"]
        indicio = bool(adequados) and max(adequados) > max(ultimo_cid, ultimo_escuro)
        if clima is None:
            clima = CondicaoClima(**{k: v for k, v in json.loads(sol["clima_json"]).items() if k != "encoberto"}) \
                if sol["clima_json"] else INDISPONIVEL
        primeiro = min((r["criado_em"] for r in relatos), default=sol["primeiro_relato_em"])
        dias = (agora() - datetime.fromisoformat(primeiro)).days if primeiro else 0
        p = calcular(evidencia, len(cid), corroborado, clima, dias)

        dados = {"evidencia": evidencia, "qtd_relatos": len(relatos), "qtd_relatos_cidadao": len(cid),
                 "corroborado_robo": int(corroborado), "indicio_reparo": int(indicio),
                 "prioridade_score": p.score, "prioridade_faixa": p.faixa,
                 "prioridade_motivos": json.dumps(p.motivos, ensure_ascii=False),
                 "clima_json": json.dumps(clima.como_dict(), ensure_ascii=False),
                 "primeiro_relato_em": primeiro}
        if redigir_texto or p.score != sol["prioridade_score"] or not sol["texto"]:
            texto, _origem = redigir({**sol, **dados}, relatos, self.cfg.llm_url, self.cfg.llm_timeout_s)
            dados["texto"] = texto
        self.repo.atualizar_solicitacao(sol_id, **dados)
        return self.repo.solicitacao(sol_id)

    def _atualizar_abertas(self) -> None:
        """Recalcula as abertas (o fator 'dias em aberto' muda com o tempo)."""
        for s in self.repo.solicitacoes([*STATUS_ABERTOS]):
            antes = s["prioridade_score"]
            depois = self._recalcular(s["id"], redigir_texto=False)
            if depois["prioridade_score"] != antes:
                self.aud.registrar("prioridade", f"{s['protocolo']}: {antes} -> {depois['prioridade_score']}",
                                   solicitacao_id=s["id"])

    # ================================================================== reprocessamento e LGPD
    def _reprocessar_pendentes(self, resumo: Resumo) -> None:
        pendentes = self.repo.relatos_por_status(StatusRelato.PENDENTE_VISAO)
        if not pendentes:
            return
        self.aud.registrar("reprocesso", f"{len(pendentes)} relato(s) pendente(s) da visão")
        for rel in pendentes:
            if self.visao.circuito_aberto:
                self.aud.registrar("reprocesso", "circuito da visão aberto; pendentes aguardam a próxima "
                                                 "execução", "WARN")
                break
            try:
                self._avaliar(rel, resumo)
            except Exception as e:  # noqa: BLE001
                resumo.falhas_inesperadas += 1
                self.aud.registrar("falha", f"reprocesso: {type(e).__name__}: {e}", "ERROR", relato_id=rel["id"])
                continue
            if self.repo.relato(rel["id"])["status"] != StatusRelato.PENDENTE_VISAO:
                resumo.reprocessados_ok += 1

    def _limpeza_lgpd(self, resumo: Resumo) -> None:
        """Apaga fotos de relatos encerrados após RETENCAO_FOTOS_DIAS (minimização de dados)."""
        limite = (agora() - timedelta(days=self.cfg.retencao_fotos_dias)).isoformat(timespec="seconds")
        rows = self.repo.conn.execute(
            "SELECT r.id, r.foto_arquivo FROM relatos r LEFT JOIN solicitacoes s ON s.id = r.solicitacao_id "
            "WHERE r.foto_arquivo IS NOT NULL AND r.atualizado_em < ? AND "
            "(r.status IN (?, ?) OR s.status IN (?, ?))",
            (limite, StatusRelato.ARQUIVADO, StatusRelato.REJEITADO_VISAO,
             StatusSolicitacao.REJEITADA, StatusSolicitacao.RESOLVIDA)).fetchall()
        for row in rows:
            (self.cfg.pasta_fotos / row["foto_arquivo"]).unlink(missing_ok=True)
            self.repo.conn.execute("UPDATE relatos SET foto_arquivo = NULL WHERE id = ?", (row["id"],))
            resumo.fotos_removidas_lgpd += 1
        if rows:
            self.aud.registrar("lgpd", f"{len(rows)} foto(s) removida(s) após {self.cfg.retencao_fotos_dias} dias")

    def _notificar(self, rel: dict, mensagem: str) -> None:
        """Outbox: o RPA não guarda o contato em claro; a API central faz o envio pelo hash."""
        if rel.get("contato_hash"):
            self.repo.inserir_notificacao(rel["id"], rel["contato_hash"], mensagem)
            self.aud.registrar("notificacao", "mensagem ao cidadão colocada na outbox", relato_id=rel["id"])
