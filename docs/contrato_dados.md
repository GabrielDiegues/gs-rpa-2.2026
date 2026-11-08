# Contrato de dados — RPA Rua Acesa

Como os outros componentes do Rua Acesa conversam com o robô. Mudanças nestes formatos precisam ser combinadas com a equipe.

## 1. Entrada: relato (`entrada/<id>.json`)

Depositado pela API central (app do cidadão) ou pelo robô de inspeção (Maker Lab). A foto, se houver, vai **na mesma pasta**, com o nome indicado em `foto`.

```json
{
  "id": "R-1001",
  "origem": "cidadao",
  "criado_em": "2026-11-08T21:40:00-03:00",
  "latitude": -23.561203,
  "longitude": -46.656997,
  "descricao": "Poste apagado em frente ao ponto de ônibus",
  "foto": "R-1001.jpg",
  "contato": "maria.exemplo@example.com"
}
```

```json
{
  "id": "R-1003",
  "origem": "robo",
  "criado_em": "2026-11-08T22:05:00-03:00",
  "latitude": -23.561212,
  "longitude": -46.657007,
  "leitura": { "dispositivo_id": "vision-wheel-01", "luminosidade_lux": 2.1, "classificacao": "escuro" }
}
```

| Campo | Tipo | Regra |
| --- | --- | --- |
| `id` | string 2–64 `[A-Za-z0-9_-]` | único; reenvio do mesmo id = duplicado |
| `origem` | `cidadao` \| `robo` | `cidadao` exige `foto`; `robo` exige `leitura` |
| `criado_em` | ISO 8601 | sem fuso = America/Sao_Paulo; não pode estar no futuro nem ter mais de 30 dias |
| `latitude`, `longitude` | número (WGS84) | dentro do município de São Paulo |
| `descricao` | string ≤ 500 | opcional; e-mails/telefones digitados aqui são mascarados |
| `foto` | nome de arquivo | sem caminho; JPEG/PNG/WebP, até 10 MB, legível |
| `contato` | string ≤ 120 | opcional; **nunca** é gravado em claro (hash + máscara) |
| `leitura.luminosidade_lux` | número 0–200 000 | o RPA reclassifica: < 5 escuro, < 15 fraco, senão adequado |
| `leitura.classificacao` | `adequado` \| `fraco` \| `escuro` | opcional (a classificação do robô); divergências são registradas no log |

Campos desconhecidos são **rejeitados** (por exemplo, um `cpf` enviado por engano não entra no sistema).

## 2. Saída para o mapa: `saida/pontos_escuros.geojson`

`FeatureCollection` das solicitações abertas (`aguardando_revisao` e `enviada`). Cada `Feature` tem `id` = protocolo, geometria `Point [lon, lat]` (coordenada do poste oficial) e as propriedades `protocolo`, `status`, `evidencia`, `prioridade_score`, `prioridade_faixa`, `qtd_relatos`, `poste_placa`, `poste_endereco`, `poste_tipo`, `indicio_reparo` e `atualizado_em`. O mesmo conteúdo sai em `GET /api/pontos` no painel.

## 3. Saída para o pipeline de dados (Airflow → Databricks)

Os arquivos são reescritos de forma atômica a cada execução. O DAG da Big Data copia para `chegada/` com a data no nome.

**`saida/solicitacoes.csv`** (uma linha por solicitação; candidato a fato):
`protocolo, status, evidencia, prioridade_score, prioridade_faixa, qtd_relatos, qtd_relatos_cidadao, corroborado_robo, indicio_reparo, poste_placa, poste_endereco, poste_tipo, poste_fonte, latitude, longitude, primeiro_relato_em, criado_em, atualizado_em, revisado_em, resolvido_em`

**`saida/relatos.csv`** (uma linha por relato aceito; pseudonimizado):
`id, origem, criado_em, recebido_em, latitude, longitude (4 casas), status, veredito, cena, confianca_apagado, classificacao_rpa, leitura_lux, poste_placa, distancia_poste_m, protocolo, contato_hash`

- `contato_hash` é HMAC-SHA256 com salt secreto: permite contar cidadãos únicos (indicador "cidadãos ativos por mês") sem identificar ninguém.
- `poste_placa` é a chave para cruzar com o cadastro do GeoSampa e com o histórico do SP156.

**`saida/indicadores.json`**: `tempo_medio_relato_reparo_h`, `pontos_escuros_ativos`, `solicitacoes_abertas`, `aguardando_revisao`, `enviadas_prefeitura`, `relatos_confirmados_ia_pct`, `duplicados_evitados` e `por_faixa`.

**`saida/fila_revisao.json`**: itens `aguardando_revisao` em ordem de prioridade, com o texto da solicitação e os motivos.

## 4. Visão computacional (consumida pelo RPA)

`POST {VISAO_URL}/detect` (multipart, campo `file`) → `{veredito, motivo, cena, brilho_medio, deteccoes[{classe, confianca, bbox}], largura, altura, modelo, tempo_ms}`. A resposta é validada com o modelo Pydantic `ResultadoVisao` (`src/rua_acesa_rpa/modelos.py`), que espelha `app/schemas.py` do repositório de visão.

## 5. Estados

| Relato (`relatos.status`) | Significado |
| --- | --- |
| `pendente_visao` | aguardando a visão voltar; reprocessado automaticamente |
| `vinculado` | faz parte de uma solicitação (nova ou existente) |
| `arquivado` | IA não confirmou, ou leitura adequada/fraca sem chamado aberto |
| `rejeitado_visao` | a visão recusou a foto |

| Solicitação (`solicitacoes.status`) | Quem muda |
| --- | --- |
| `aguardando_revisao` | robô (ao criar) |
| `enviada` | revisor(a) no painel (aprovar) |
| `rejeitada` | revisor(a), com motivo |
| `resolvida` | revisor(a), quando o poste é religado; alimenta o indicador de tempo de reparo |
