# Roteiro do vídeo (até 3 minutos)

| Tempo | Tela | Fala (resumo) |
| --- | --- | --- |
| 0:00–0:20 | Painel / foto de rua escura | "Poste apagado deixa o caminho a pé inseguro à noite. Hoje alguém precisa ler cada reclamação, olhar a foto, achar o poste, ver se já tem chamado e decidir a urgência." |
| 0:20–0:35 | `docs/fluxo_rpa.svg` | "O robô do Rua Acesa faz isso em lote: valida, confirma com a IA de visão, acha o poste oficial no GeoSampa, junta repetidos, prioriza pelo clima e redige a solicitação. A pessoa só aprova." |
| 0:35–1:20 | Terminal: API de visão rodando + `gerar_lote_demo.py` + `processar` | Mostrar no log: confirmado → poste IP… a 3 m → nova solicitação; segundo relato **agrupado** (deduplicação); robô "escuro" sobe a prioridade (**regra de decisão**); foto diurna inconclusiva; JSON inválido, foto ausente e fora de SP indo para `erros/`; foto repetida = duplicado. Fechar com o resumo da execução. |
| 1:20–1:50 | Derrubar a visão (Ctrl+C) → `gerar_lote_demo.py --lote 2` → `processar` | **Tratamento de falha:** 3 tentativas com backoff, relato fica `pendente_visao`, lote termina. Religar a visão → `reprocessar-pendentes` → confirmado e agrupado. |
| 1:50–2:35 | Navegador `localhost:8001` | **Integração com o MVP:** fila priorizada com fotos, veredito, lux do robô, motivos e texto do SP156. Aprovar RA-…-000001 (indício de reparo) → "Enviadas" → marcar resolvida → indicador "tempo médio relato → reparo" aparece. Mapa dos pontos escuros. |
| 2:35–2:55 | `logs/*.jsonl`, `saida/` | Logs de auditoria sem e-mail/telefone (mostrar `contato_hash`), exports GeoJSON/CSV que alimentam o mapa e o Databricks. `pytest`: 75 testes passando. |
| 2:55–3:00 | — | "Menos trabalho manual, nenhum chamado duplicado e a pessoa decide com tudo na mão." |

Antes de gravar: apague o estado (`rm -rf dados/rua_acesa.db* dados/fotos processados erros saida/*.* logs/*.jsonl`), suba a visão e deixe dois terminais abertos.
