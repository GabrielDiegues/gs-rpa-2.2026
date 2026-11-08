# Testes e validação

```bash
pytest                 # 75 testes, ~1 s, sem rede (APIs externas simuladas)
pytest -m integracao   # 3 testes contra a API de visão REAL (suba antes a API de visão)
```

Os dublês (`conftest.py`) seguem os contratos reais: o JSON de `/detect` do repositório de visão, o GeoJSON do WFS do GeoSampa (placa repetida por luminária) e as listas paralelas do Open-Meteo.

Saída completa da última execução: [`evidencias/pytest_saida.txt`](evidencias/pytest_saida.txt).

## Cenários cobertos

### Sucesso
| Teste | O que prova |
| --- | --- |
| `test_pipeline::test_lote_completo_sucesso` | lote misto de ponta a ponta: estados, deduplicação, evidências, protocolo, arquivos movidos, exports, outbox |
| `test_pipeline::test_prioridade_maior_quando_relatos_se_acumulam` | novos relatos + robô somam +6 e +15 na mesma solicitação |
| `test_integracoes::test_visao_sucesso`, `test_poste_mais_proximo_via_wfs_sem_placa_repetida`, `test_clima_noite_chuvosa_e_cache` | cada integração no caminho feliz |
| `test_integracao_visao::test_veredito_real` (×3) | **API de visão real**: confirmado, não confirmado e inconclusivo (dia) |
| `test_painel::*` | aprovar → enviada + auditoria + notificação; resolver → indicador de tempo de reparo |

### Decisão (regras de negócio)
| Teste | O que prova |
| --- | --- |
| `test_regras::test_*prioridade*`, `test_limites_das_faixas` | tabela de pontuação, tetos e faixas |
| `test_regras::test_classificacao_do_ldr` | limiares de lux nas bordas |
| `test_pipeline::test_robo_adequado_depois_do_relato_indica_reparo` | RN04, indício de reparo |
| `test_pipeline::test_robo_sem_solicitacao_aberta_e_arquivado_e_divergencia_logada` | reclassificação do LDR + WARN |
| `test_pipeline::test_rodar_de_novo_nao_duplica`, `test_mesma_foto_com_outro_id_e_duplicada` | idempotência por id e por foto |
| `test_regras::test_dedup_por_distancia_quando_nao_ha_poste` | deduplicação sem poste; só solicitações abertas agrupam |
| `test_painel::test_rejeitar_exige_motivo`, `test_transicao_invalida_retorna_409` | RN06/RN07 e máquina de estados |

### Falha e resiliência
| Teste | O que prova |
| --- | --- |
| `test_integracoes::test_visao_retry_com_backoff_exponencial` | 2 timeouts → 3ª tentativa ok; esperas 1 s e 2 s |
| `test_integracoes::test_visao_fora_do_ar_e_circuito_abre` | circuit breaker: depois de aberto, não chama mais |
| `test_integracoes::test_visao_5xx_e_repetido`, `test_visao_foto_recusada_nao_repete`, `test_visao_resposta_fora_do_contrato_nao_repete` | o que repete e o que não repete |
| `test_pipeline::test_visao_fora_fica_pendente_e_e_reprocessada` | visão fora → `pendente_visao` → volta → reprocessados e agrupados |
| `test_pipeline::test_open_meteo_e_geosampa_fora_nao_param_o_robo` | fallback para CSV, prioridade sem clima, um aviso por integração |
| `test_integracoes::test_wfs_fora_usa_cache`, `test_wfs_fora_sem_cache_usa_recorte_csv`, `test_clima_*_degrada` | degradação de cada integração |
| `test_pipeline::test_falha_inesperada_isolada_no_item` | um item explode, os outros seguem; relato desfeito para reenvio; `concluida_com_falhas` |
| `test_validacao::*` (14) | JSON quebrado/vazio, sem foto, foto ausente/corrompida/grande, caminho malicioso, fora de SP, futuro, antigo, LDR negativo, campo extra |
| `test_pipeline::test_invalidos_vao_para_erros_com_motivo` | `erros/<execução>/` com `.erro.txt` e a foto junto |
| `test_pipeline::test_lote_limitado_deixa_restante_para_proxima` | `MAX_LOTE` |

### LGPD e auditoria
| Teste | O que prova |
| --- | --- |
| `test_pipeline::test_contato_nunca_em_claro_e_foto_sem_exif` | contato só como hash/máscara, descrição sanitizada, nada em claro em logs/exports, EXIF removido |
| `test_regras::test_hash_*`, `test_mascaras`, `test_sanitizar_*`, `test_foto_regravada_sem_exif` | funções de proteção |
| `test_pipeline::test_log_jsonl_tem_campos_de_auditoria` | campos obrigatórios e etapas do log |
| `test_painel::test_api_nao_expoe_contato`, `test_foto_servida_e_path_traversal_bloqueado` | API do painel sem dado pessoal e sem *path traversal* |

## Execução de ponta a ponta (manual, com serviços reais)

Saídas reais em [`../assets/terminal/`](../assets/terminal/): lote 1 com visão + GeoSampa + Open-Meteo reais; lote 2 com a visão desligada; reprocessamento depois que ela volta.
