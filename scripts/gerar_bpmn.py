"""Gera o desenho do processo em BPMN 2.0 a partir de uma única definição:

- docs/fluxo_rpa.bpmn : XML BPMN 2.0 com diagrama (DI) — abre no bpmn.io / Camunda Modeler
- docs/fluxo_rpa.svg  : a mesma figura para o README e o relatório

    python scripts/gerar_bpmn.py
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs"

TAM = {"task": (104, 66), "service": (104, 66), "user": (104, 66), "gateway": (46, 46),
       "start_timer": (36, 36), "start_message": (36, 36), "start": (36, 36), "end": (36, 36),
       "end_message": (36, 36)}


def col(i: float) -> float:
    return 140 + i * 118


TOPO, SPINE, R1, R2, POS = 190, 300, 410, 520, 665
YB = 860  # linha do painel

# ------------------------------------------------------------------ participantes
POOLS = {
    "visao": {"nome": "API de Visão (YOLO)", "x": col(8) - 95, "y": 20, "w": 190, "h": 56},
    "geosampa": {"nome": "GeoSampa WFS (postes)", "x": col(11) - 95, "y": 20, "w": 190, "h": 56},
    "meteo": {"nome": "Open-Meteo (clima)", "x": col(13) - 80, "y": 20, "w": 190, "h": 56},
    "rpa": {"nome": "Robô RPA Rua Acesa (Python)", "x": 30, "y": 110, "w": col(15) + 75 - 30, "h": 615,
            "processo": "Processo_RPA"},
    "painel": {"nome": "Revisão humana (painel)", "x": 30, "y": 760, "w": col(15) + 75 - 30, "h": 200,
               "processo": "Processo_Revisao"},
}
SUB = {"id": "SP1", "nome": "Para cada relato do lote (multi-instância sequencial)",
       "x": col(3) - 50, "y": 140, "w": col(15) + 45 - (col(3) - 50), "h": 450, "pool": "rpa"}

# ------------------------------------------------------------------ nós (id: tipo, nome, x, y, contêiner)
# contêiner: pool (rpa/painel) ou "SP1" (dentro do subprocesso)
NOS = {
    "S1": ("start_timer", "Agendamento\n(a cada N min)", col(0), SPINE, "rpa"),
    "T1": ("task", "Reprocessar\npendentes da\nvisão", col(1), SPINE, "rpa"),
    "T2": ("task", "Ler lote de\nentrada/\n(JSON + foto)", col(2), SPINE, "rpa"),
    "T10": ("task", "Recalcular\nabertas + LGPD\n(retenção)", col(12), POS, "rpa"),
    "T11": ("task", "Exportar saida/\n+ resumo da\nexecução", col(13), POS, "rpa"),
    "E1": ("end", "Lote\nconcluído", col(14), POS, "rpa"),
    # ---- subprocesso: um relato
    "SS": ("start", "Relato", col(3), SPINE, "SP1"),
    "T3": ("task", "Validar relato\n(schema, SP,\nfoto, data)", col(4), SPINE, "SP1"),
    "G2": ("gateway", "Válido?", col(5), SPINE, "SP1"),
    "G3": ("gateway", "Já recebido?", col(6), SPINE, "SP1"),
    "G4": ("gateway", "Origem?", col(7), SPINE, "SP1"),
    "T4": ("service", "Confirmar foto\n(POST /detect)\nretry + circuito", col(8), SPINE, "SP1"),
    "G5": ("gateway", "Veredito?", col(9), SPINE, "SP1"),
    "GM": ("gateway", "", col(10), SPINE, "SP1"),
    "T6": ("service", "Localizar poste\noficial mais\npróximo", col(11), SPINE, "SP1"),
    "T7": ("task", "Deduplicar\n(1 solicitação\npor poste)", col(12), SPINE, "SP1"),
    "T8": ("service", "Clima noturno +\ncalcular\nprioridade", col(13), SPINE, "SP1"),
    "T9": ("task", "Redigir texto\nSP156 e gravar\nsolicitação", col(14), SPINE, "SP1"),
    "EF": ("end_message", "Na fila de\nrevisão", col(15), SPINE, "SP1"),
    "EI": ("end", "Inválido →\nerros/ + motivo", col(5), R1, "SP1"),
    "ED": ("end", "Duplicado\n(descartado)", col(6), R1, "SP1"),
    "EP": ("end", "Pendente: visão\nfora (reprocessa)", col(9), R1, "SP1"),
    "T4a": ("task", "Arquivar +\navisar cidadão\n(outbox)", col(9) + 18, TOPO, "SP1"),
    "EA": ("end", "Arquivado", col(10) + 40, TOPO, "SP1"),
    "T5": ("task", "Classificar\nleitura LDR\n(lux)", col(8), R2, "SP1"),
    "G6": ("gateway", "Escuro?", col(9), R2, "SP1"),
    "T5a": ("task", "Indício de\nreparo ou\narquivar", col(10) + 20, R2, "SP1"),
    "ER": ("end", "Leitura\nregistrada", col(11) + 30, R2, "SP1"),
    # ---- painel
    "S2": ("start_message", "Nova\nsolicitação", col(8), YB, "painel"),
    "U1": ("user", "Revisar foto,\nveredito e\nprioridade", col(9), YB, "painel"),
    "G7": ("gateway", "Decisão?", col(10), YB, "painel"),
    "U2": ("user", "Aprovar e enviar\nà Prefeitura\n(SP156)", col(11), YB - 45, "painel"),
    "U3": ("user", "Marcar resolvida\n(poste religado)", col(12), YB - 45, "painel"),
    "E2": ("end", "Resolvida", col(13), YB - 45, "painel"),
    "U4": ("user", "Rejeitar\ncom motivo", col(11), YB + 50, "painel"),
    "E3": ("end", "Rejeitada", col(12), YB + 50, "painel"),
}
# rótulos de gateway: deslocamento (dx, dy) em relação ao centro
ROTULO_GW = {"G7": (-30, 40), "G5": (-14, 40), "G4": (-6, -40), "G2": (-6, -40), "G3": (-6, -40),
             "G6": (30, 26)}


def caixa(n):
    tipo, _, x, y, _ = NOS[n]
    w, h = TAM[tipo]
    return x - w / 2, y - h / 2, w, h


def R(n):
    x, y, w, h = caixa(n)
    return (x + w, y + h / 2)


def L(n):
    x, y, w, h = caixa(n)
    return (x, y + h / 2)


def T(n):
    x, y, w, h = caixa(n)
    return (x + w / 2, y)


def B(n):
    x, y, w, h = caixa(n)
    return (x + w / 2, y + h)


def pool_de(n: str) -> str:
    c = NOS[n][4]
    return SUB["pool"] if c == SUB["id"] else c


SUB_L = (SUB["x"], SPINE)
SUB_B = (col(12), SUB["y"] + SUB["h"])

# ------------------------------------------------------------------ fluxos de sequência (id: origem, destino, rótulo, pontos)
FLUXOS = {
    "f1": ("S1", "T1", "", [R("S1"), L("T1")]),
    "f2": ("T1", "T2", "", [R("T1"), L("T2")]),
    "f3": ("T2", "SP1", "", [R("T2"), SUB_L]),
    "f4": ("SP1", "T10", "lote terminado", [SUB_B, T("T10")]),
    "f5": ("T10", "T11", "", [R("T10"), L("T11")]),
    "f6": ("T11", "E1", "", [R("T11"), L("E1")]),
    # subprocesso
    "s1": ("SS", "T3", "", [R("SS"), L("T3")]),
    "s2": ("T3", "G2", "", [R("T3"), L("G2")]),
    "s3": ("G2", "G3", "sim", [R("G2"), L("G3")]),
    "s4": ("G2", "EI", "não", [B("G2"), T("EI")]),
    "s5": ("G3", "G4", "não", [R("G3"), L("G4")]),
    "s6": ("G3", "ED", "sim (id\nou foto)", [B("G3"), T("ED")]),
    "s7": ("G4", "T4", "cidadão", [R("G4"), L("T4")]),
    "s8": ("G4", "T5", "robô", [B("G4"), (B("G4")[0], R2), L("T5")]),
    "s9": ("T4", "G5", "", [R("T4"), L("G5")]),
    "s10": ("G5", "GM", "confirmado /\ninconclusivo", [R("G5"), L("GM")]),
    "s11": ("G5", "EP", "visão fora", [B("G5"), T("EP")]),
    "s12": ("G5", "T4a", "não confirmado", [T("G5"), (T("G5")[0], TOPO), L("T4a")]),
    "s13": ("T4a", "EA", "", [R("T4a"), L("EA")]),
    "s14": ("T5", "G6", "", [R("T5"), L("G6")]),
    "s15": ("G6", "GM", "sim", [T("G6"), (T("G6")[0], (R1 + R2) / 2 + 10), (col(10), (R1 + R2) / 2 + 10), B("GM")]),
    "s16": ("G6", "T5a", "não", [R("G6"), L("T5a")]),
    "s17": ("T5a", "ER", "", [R("T5a"), L("ER")]),
    "s18": ("GM", "T6", "", [R("GM"), L("T6")]),
    "s19": ("T6", "T7", "", [R("T6"), L("T7")]),
    "s20": ("T7", "T8", "", [R("T7"), L("T8")]),
    "s21": ("T8", "T9", "", [R("T8"), L("T9")]),
    "s22": ("T9", "EF", "", [R("T9"), L("EF")]),
    # painel
    "p1": ("S2", "U1", "", [R("S2"), L("U1")]),
    "p2": ("U1", "G7", "", [R("U1"), L("G7")]),
    "p3": ("G7", "U2", "aprovar", [T("G7"), (T("G7")[0], YB - 45), L("U2")]),
    "p4": ("G7", "U4", "rejeitar", [B("G7"), (B("G7")[0], YB + 50), L("U4")]),
    "p5": ("U2", "U3", "", [R("U2"), L("U3")]),
    "p6": ("U3", "E2", "", [R("U3"), L("E2")]),
    "p7": ("U4", "E3", "", [R("U4"), L("E3")]),
}

# fluxos de mensagem (entre participantes)
MENSAGENS = {
    "m1": ("T4", "visao", "foto", [T("T4"), (T("T4")[0], 76)]),
    "m2": ("T6", "geosampa", "bbox", [T("T6"), (T("T6")[0], 76)]),
    "m3": ("T8", "meteo", "lat/lon", [T("T8"), (T("T8")[0], 76)]),
    "m4": ("EF", "S2", "solicitação na fila", [B("EF"), (B("EF")[0], 742), (col(8), 742), T("S2")]),
}

TAG_BPMN = {"task": "task", "service": "serviceTask", "user": "userTask", "gateway": "exclusiveGateway",
            "start_timer": "startEvent", "start_message": "startEvent", "start": "startEvent", "end": "endEvent",
            "end_message": "endEvent"}


# ================================================================== BPMN XML
def _no_xml(nid: str, ind: str) -> str:
    tipo, nome, *_ = NOS[nid]
    tag = TAG_BPMN[tipo]
    corpo = "".join(f"<bpmn:incoming>{f}</bpmn:incoming>" for f, v in FLUXOS.items() if v[1] == nid)
    corpo += "".join(f"<bpmn:outgoing>{f}</bpmn:outgoing>" for f, v in FLUXOS.items() if v[0] == nid)
    if tipo == "start_timer":
        corpo += ('<bpmn:timerEventDefinition id="Timer_S1"><bpmn:timeCycle>R/PT5M</bpmn:timeCycle>'
                  "</bpmn:timerEventDefinition>")
    if tipo in ("start_message", "end_message"):
        corpo += f'<bpmn:messageEventDefinition id="Msg_{nid}" />'
    return f'{ind}<bpmn:{tag} id="{nid}" name="{escape(nome.replace(chr(10), " "))}">{corpo}</bpmn:{tag}>'


def _fluxo_xml(fid: str, ind: str) -> str:
    src, dst, nome, _ = FLUXOS[fid]
    n = f' name="{escape(nome.replace(chr(10), " "))}"' if nome else ""
    return f'{ind}<bpmn:sequenceFlow id="{fid}"{n} sourceRef="{src}" targetRef="{dst}" />'


def _conteiner(n: str) -> str:
    return SUB["id"] if n == SUB["id"] else NOS[n][4]


def gerar_bpmn() -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
           'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
           'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definicoes_RuaAcesa" '
           'targetNamespace="https://github.com/rua-acesa/rpa" exporter="scripts/gerar_bpmn.py" exporterVersion="1.0">',
           '  <bpmn:collaboration id="Colaboracao_RuaAcesa">']
    for pid, p in POOLS.items():
        ref = f' processRef="{p["processo"]}"' if "processo" in p else ""
        out.append(f'    <bpmn:participant id="Pool_{pid}" name="{escape(p["nome"])}"{ref} />')
    for mid, (src, dst, nome, _) in MENSAGENS.items():
        alvo = dst if dst in NOS else f"Pool_{dst}"
        out.append(f'    <bpmn:messageFlow id="{mid}" name="{escape(nome)}" sourceRef="{src}" targetRef="{alvo}" />')
    out.append("  </bpmn:collaboration>")

    for pid, p in POOLS.items():
        if "processo" not in p:
            continue
        out.append(f'  <bpmn:process id="{p["processo"]}" name="{escape(p["nome"])}" isExecutable="false">')
        out += [_no_xml(n, "    ") for n in NOS if NOS[n][4] == pid]
        if SUB["pool"] == pid:
            ent = "".join(f"<bpmn:incoming>{f}</bpmn:incoming>" for f, v in FLUXOS.items() if v[1] == SUB["id"])
            sai = "".join(f"<bpmn:outgoing>{f}</bpmn:outgoing>" for f, v in FLUXOS.items() if v[0] == SUB["id"])
            out.append(f'    <bpmn:subProcess id="{SUB["id"]}" name="{escape(SUB["nome"])}">{ent}{sai}')
            out.append('      <bpmn:multiInstanceLoopCharacteristics isSequential="true" />')
            out += [_no_xml(n, "      ") for n in NOS if NOS[n][4] == SUB["id"]]
            out += [_fluxo_xml(f, "      ") for f, v in FLUXOS.items() if _conteiner(v[0]) == SUB["id"]]
            out.append("    </bpmn:subProcess>")
        out += [_fluxo_xml(f, "    ") for f, v in FLUXOS.items()
                if _conteiner(v[0]) == pid or (v[0] == SUB["id"] and SUB["pool"] == pid)]
        out.append("  </bpmn:process>")

    out += ['  <bpmndi:BPMNDiagram id="Diagrama_RuaAcesa">',
            '    <bpmndi:BPMNPlane id="Plano_RuaAcesa" bpmnElement="Colaboracao_RuaAcesa">']
    for pid, p in POOLS.items():
        out.append(f'      <bpmndi:BPMNShape id="Pool_{pid}_di" bpmnElement="Pool_{pid}" isHorizontal="true">'
                   f'<dc:Bounds x="{p["x"]:.0f}" y="{p["y"]:.0f}" width="{p["w"]:.0f}" height="{p["h"]:.0f}" />'
                   "</bpmndi:BPMNShape>")
    out.append(f'      <bpmndi:BPMNShape id="{SUB["id"]}_di" bpmnElement="{SUB["id"]}" isExpanded="true">'
               f'<dc:Bounds x="{SUB["x"]:.0f}" y="{SUB["y"]:.0f}" width="{SUB["w"]:.0f}" height="{SUB["h"]:.0f}" />'
               "</bpmndi:BPMNShape>")
    for nid, (tipo, *_r) in NOS.items():
        x, y, w, h = caixa(nid)
        extra = ' isMarkerVisible="true"' if tipo == "gateway" else ""
        label = ""
        if tipo not in ("task", "service", "user"):
            label = (f'<bpmndi:BPMNLabel><dc:Bounds x="{x - 30:.0f}" y="{y + h + 4:.0f}" width="{w + 60:.0f}" '
                     f'height="28" /></bpmndi:BPMNLabel>')
        out.append(f'      <bpmndi:BPMNShape id="{nid}_di" bpmnElement="{nid}"{extra}>'
                   f'<dc:Bounds x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" />{label}</bpmndi:BPMNShape>')
    for fid, (*_r, pts) in {**FLUXOS, **MENSAGENS}.items():
        wps = "".join(f'<di:waypoint x="{px:.0f}" y="{py:.0f}" />' for px, py in pts)
        out.append(f'      <bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">{wps}</bpmndi:BPMNEdge>')
    out += ["    </bpmndi:BPMNPlane>", "  </bpmndi:BPMNDiagram>", "</bpmn:definitions>", ""]
    return "\n".join(out)


# ================================================================== SVG
COR = {"linha": "#22262e", "pool": "#f8f9fb", "faixa": "#e9ecf1", "task": "#ffffff", "service": "#eef5ff",
       "user": "#fff6e6", "texto": "#14181f", "rotulo": "#4a5260", "msg": "#5b6472", "fim": "#b42318",
       "ini": "#1d6f42", "sub": "#ffffff"}


def _texto(x, y, txt, tam=12, peso="normal", cor=None, ancora="middle"):
    linhas = txt.split("\n")
    y0 = y - (len(linhas) - 1) * tam * 0.6
    spans = "".join(f'<tspan x="{x:.0f}" y="{y0 + i * tam * 1.2:.0f}">{escape(l)}</tspan>' for i, l in enumerate(linhas))
    return (f'<text font-family="DejaVu Sans, Arial, sans-serif" font-size="{tam}" font-weight="{peso}" '
            f'fill="{cor or COR["texto"]}" text-anchor="{ancora}" dominant-baseline="middle">{spans}</text>')


def _seta(pts, tracejado=False):
    d = "M " + " L ".join(f"{x:.0f} {y:.0f}" for x, y in pts)
    if tracejado:
        return (f'<path d="{d}" fill="none" stroke="{COR["msg"]}" stroke-width="1.4" stroke-dasharray="6 4" '
                f'marker-start="url(#circulo)" marker-end="url(#seta-vazia)"/>')
    return f'<path d="{d}" fill="none" stroke="{COR["linha"]}" stroke-width="1.5" marker-end="url(#seta)"/>'


def _rotulo_fluxo(pts, txt):
    if not txt:
        return ""
    (x1, y1), (x2, y2) = pts[0], pts[1]
    if abs(y1 - y2) < 1:  # horizontal: acima da linha
        return _texto((x1 + x2) / 2, y1 - 13, txt, 10.5, cor=COR["rotulo"])
    return _texto(x1 + 6, (y1 + y2) / 2, txt, 10.5, cor=COR["rotulo"], ancora="start")


def _evento(tipo, x, y):
    fim = tipo.startswith("end")
    out = [f'<circle cx="{x:.0f}" cy="{y:.0f}" r="18" fill="#fff" stroke="{COR["fim"] if fim else COR["ini"]}" '
           f'stroke-width="{4 if fim else 1.8}"/>']
    if tipo == "start_timer":
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="12" fill="none" stroke="{COR["linha"]}"/>'
                   f'<path d="M{x:.0f},{y - 9:.0f} L{x:.0f},{y:.0f} L{x + 6:.0f},{y + 3:.0f}" fill="none" '
                   f'stroke="{COR["linha"]}" stroke-width="1.6"/>')
    if tipo in ("start_message", "end_message"):
        cheio = tipo == "end_message"
        out.append(f'<rect x="{x - 10:.0f}" y="{y - 7:.0f}" width="20" height="14" fill="{COR["linha"] if cheio else "none"}" '
                   f'stroke="{COR["linha"]}"/><path d="M{x - 10:.0f},{y - 7:.0f} L{x:.0f},{y + 1:.0f} L{x + 10:.0f},{y - 7:.0f}" '
                   f'fill="none" stroke="{"#fff" if cheio else COR["linha"]}"/>')
    return "".join(out)


def gerar_svg() -> str:
    W = col(15) + 90
    H = 980
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H}" width="{W:.0f}" height="{H}">',
         "<defs>",
         f'<marker id="seta" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="{COR["linha"]}"/></marker>',
         f'<marker id="seta-vazia" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="9" markerHeight="9" orient="auto">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="#fff" stroke="{COR["msg"]}"/></marker>',
         f'<marker id="circulo" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="7" markerHeight="7">'
         f'<circle cx="5" cy="5" r="4" fill="#fff" stroke="{COR["msg"]}"/></marker>',
         "</defs>", f'<rect width="{W:.0f}" height="{H}" fill="#ffffff"/>']
    for pid, pool in POOLS.items():
        x, y, w, h = pool["x"], pool["y"], pool["w"], pool["h"]
        p.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" fill="{COR["pool"]}" '
                 f'stroke="{COR["linha"]}" stroke-width="1.4"/>')
        if "processo" in pool:
            p.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="30" height="{h:.0f}" fill="{COR["faixa"]}" '
                     f'stroke="{COR["linha"]}" stroke-width="1.4"/>')
            cx, cy = x + 15, y + h / 2
            p.append(f'<g transform="rotate(-90 {cx:.0f} {cy:.0f})">{_texto(cx, cy, pool["nome"], 13, "bold")}</g>')
        else:
            p.append(_texto(x + w / 2, y + h / 2, pool["nome"], 12.5, "bold"))
    # subprocesso expandido + marcador multi-instância sequencial (≡)
    sx, sy, sw, sh = SUB["x"], SUB["y"], SUB["w"], SUB["h"]
    p.append(f'<rect x="{sx:.0f}" y="{sy:.0f}" width="{sw:.0f}" height="{sh:.0f}" rx="14" fill="{COR["sub"]}" '
             f'stroke="{COR["linha"]}" stroke-width="1.6"/>')
    p.append(_texto(sx + 14, sy + 18, SUB["nome"], 12.5, "bold", ancora="start"))
    mx, my = sx + sw / 2, sy + sh - 18
    p.append("".join(f'<path d="M{mx - 8:.0f},{my + d:.0f} L{mx + 8:.0f},{my + d:.0f}" stroke="{COR["linha"]}" '
                     f'stroke-width="2.2"/>' for d in (-6, 0, 6)))
    for fid, (*_r, nome, pts) in FLUXOS.items():
        p.append(_seta(pts))
        p.append(_rotulo_fluxo(pts, nome))
    for mid, (*_r, nome, pts) in MENSAGENS.items():
        p.append(_seta(pts, tracejado=True))
        if mid == "m4":
            p.append(_texto(col(12), 732, nome, 10.5, cor=COR["msg"]))
        else:
            p.append(_texto(pts[0][0] + 6, 92, nome, 10.5, cor=COR["msg"], ancora="start"))
    for nid, (tipo, nome, x, y, _c) in NOS.items():
        bx, by, w, h = caixa(nid)
        if tipo in ("task", "service", "user"):
            p.append(f'<rect x="{bx:.0f}" y="{by:.0f}" width="{w}" height="{h}" rx="10" fill="{COR[tipo]}" '
                     f'stroke="{COR["linha"]}" stroke-width="1.5"/>')
            if tipo == "service":
                p.append(f'<circle cx="{bx + 11:.0f}" cy="{by + 11:.0f}" r="5" fill="none" stroke="{COR["linha"]}" '
                         f'stroke-width="2" stroke-dasharray="2.2 1.6"/>')
            if tipo == "user":
                p.append(f'<circle cx="{bx + 11:.0f}" cy="{by + 8:.0f}" r="3.4" fill="none" stroke="{COR["linha"]}"/>'
                         f'<path d="M{bx + 4:.0f},{by + 19:.0f} q7,-10 14,0" fill="none" stroke="{COR["linha"]}"/>')
            p.append(_texto(x, y + 2, nome, 11))
        elif tipo == "gateway":
            p.append(f'<polygon points="{x:.0f},{by:.0f} {bx + w:.0f},{y:.0f} {x:.0f},{by + h:.0f} {bx:.0f},{y:.0f}" '
                     f'fill="#fffbe6" stroke="{COR["linha"]}" stroke-width="1.5"/>')
            p.append(f'<path d="M{x - 8:.0f},{y - 8:.0f} L{x + 8:.0f},{y + 8:.0f} M{x + 8:.0f},{y - 8:.0f} '
                     f'L{x - 8:.0f},{y + 8:.0f}" stroke="{COR["linha"]}" stroke-width="2.4"/>')
            if nome:
                dx, dy = ROTULO_GW.get(nid, (-6, -40))
                p.append(_texto(x + dx, y + dy, nome, 10.5, "bold", ancora="end" if dx < 0 else "start"))
        else:
            p.append(_evento(tipo, x, y))
            p.append(_texto(x, y - 40 if nid == "EF" else y + 38, nome, 10.5))
    p.append("</svg>")
    return "\n".join(p)


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    (DOCS / "fluxo_rpa.bpmn").write_text(gerar_bpmn(), encoding="utf-8")
    (DOCS / "fluxo_rpa.svg").write_text(gerar_svg(), encoding="utf-8")
    print("docs/fluxo_rpa.bpmn e docs/fluxo_rpa.svg gerados "
          f"({len(NOS)} elementos, {len(FLUXOS)} fluxos, {len(MENSAGENS)} mensagens)")


if __name__ == "__main__":
    main()
