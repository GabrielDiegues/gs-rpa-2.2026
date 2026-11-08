# PDD — Process Definition Document

**Processo:** triagem e encaminhamento de relatos de iluminação pública (Rua Acesa)
**Componente:** Automação (RPA) · **Tecnologia:** Python 3.12 · **Versão:** 1.0 · nov/2026

## 1. Visão geral

| Item | Descrição |
| --- | --- |
| Objetivo | Transformar relatos brutos (fotos de cidadãos e leituras do robô de inspeção) em solicitações de reparo confirmadas, deduplicadas, priorizadas e prontas para o SP156 |
| Gatilho | Agendamento (`agendar --intervalo N`, padrão 5 min) ou execução sob demanda (`processar`) |
| Entradas | `entrada/*.json` (+ foto) · API de visão (YOLO) · GeoSampa WFS · Open-Meteo |
| Saídas | Solicitações no SQLite (fila do painel) · `saida/` (GeoJSON, CSV, indicadores) · outbox de notificações · logs JSONL |
| Intervenção humana | Só na decisão final (aprovar/rejeitar/resolver), no painel |
| Volume de referência | Lote de até 200 relatos por execução (`MAX_LOTE`) |

## 2. Processo atual (AS-IS, manual)

1. Atendente abre cada reclamação recebida.
2. Abre a foto e julga se o poste está apagado; não percebe se a foto foi tirada de dia.
3. Procura o poste no cadastro pelo endereço digitado.
4. Procura chamados abertos para não duplicar.
5. Decide a urgência por intuição.
6. Redige o texto e abre o chamado.

Dores: tempo por relato, chamados duplicados, falsos positivos (foto diurna), urgência sem critério e nenhum rastro de auditoria.

## 3. Processo automatizado (TO-BE)

Diagrama: [`fluxo_rpa.bpmn`](fluxo_rpa.bpmn) / [`fluxo_rpa.svg`](fluxo_rpa.svg).

| # | Passo | Sistema | Regra / decisão | Exceção → tratamento |
| --- | --- | --- | --- | --- |
| 0 | Reprocessar `pendente_visao` | SQLite, visão | só se o circuito da visão estiver fechado | visão ainda fora → continuam pendentes |
| 1 | Ler lote | `entrada/` | ordem de chegada; até `MAX_LOTE` | excedente → próxima execução |
| 2 | **Para cada relato** (laço) | — | — | erro inesperado → item vai para `erros/`, lote segue |
| 2.1 | Validar | Pydantic, Pillow | schema estrito, SP, data, foto | inválido → `erros/` + `.erro.txt` |
| 2.2 | Idempotência | SQLite | id ou SHA-256 da foto já vistos | duplicado → `processados/.../duplicados/` |
| 2.3 | Decidir pela origem | — | cidadão → visão; robô → LDR | — |
| 2.4a | Confirmar foto | API YOLO | confirmado / não confirmado / inconclusivo | retry 3× (backoff 1 s, 2 s), circuit breaker → `pendente_visao`; 4xx da foto → `rejeitado_visao` |
| 2.4b | Classificar LDR | regra | < 5 lux escuro; < 15 fraco; senão adequado | divergência com o robô → WARN |
| 2.5 | Poste oficial | GeoSampa WFS | mais próximo em 40 m | WFS fora → cache → CSV |
| 2.6 | Deduplicar | SQLite | 1 solicitação aberta por placa (sem poste: 30 m) | — |
| 2.7 | Prioridade | Open-Meteo | tabela de pontuação (README) | clima fora → fator ignorado e explicado |
| 2.8 | Redigir solicitação | template / LLM | protocolo `RA-AAAA-NNNNNN` | LLM fora → template |
| 3 | Recalcular abertas, LGPD, exportar | SQLite, `saida/` | +1 ponto/dia em aberto; apaga fotos vencidas | — |
| 4 | Revisão humana | painel | aprovar / rejeitar (motivo) / resolver | transição inválida → 409 |

## 4. Regras de negócio

- **RN01** Relato de cidadão sem foto não é aceito; relato do robô sem leitura também não.
- **RN02** Foto diurna nunca confirma defeito (poste desligado de dia é o esperado): fica inconclusiva e o cidadão recebe um pedido de nova foto à noite.
- **RN03** Uma solicitação aberta por poste. Novos relatos só aumentam a prioridade.
- **RN04** Leitura "adequada" do robô depois do último relato de escuro marca **indício de reparo** (fecha o ciclo e ajuda a medir o tempo de reparo).
- **RN05** Prioridade conforme a tabela; faixas alta ≥ 70, média ≥ 45.
- **RN06** Nada é enviado à Prefeitura sem aprovação humana registrada (nome e horário).
- **RN07** Rejeição exige motivo.

## 5. Requisitos não funcionais

- **Idempotência:** rodar de novo não duplica relatos nem solicitações (testado).
- **Atomicidade:** criação da solicitação e vínculo do relato numa transação; exports gravados de forma atômica.
- **Observabilidade:** log JSONL por passo, resumo por execução e trilha no painel.
- **LGPD:** contato só como hash/máscara, foto sem EXIF, retenção configurável e logs sem dados pessoais.
- **Configuração:** tudo no `.env`, com padrões seguros.
