# Integration Incident Monitor

Aplicação demonstrativa para receber eventos fictícios de integrações, detectar falhas repetidas, acompanhar incidentes e observar entregas simuladas. O destino de entrega é local e determinístico: **nenhum sistema externo, cliente, telefone ou dado da Eazytech é usado**.

## Executar

Requer Docker com Compose. Copie `.env.example` para `.env` e execute, na raiz:

```bash
docker compose up --build
```

- **Interface:** http://localhost:8080
- **Documentação da API:** http://localhost:8000/docs
- **Health check da API:** http://localhost:8000/health

O Compose inicia PostgreSQL, aplica as migrações versionadas, inicia API, worker e frontend. O frontend Nginx encaminha `/api/` à API; o navegador não recebe a URL do banco nem segredos. O volume `incident_pgdata` preserva os dados entre recriações de contêineres. Para parar sem apagar o volume: `docker compose down`. Para recriar: `docker compose up --build`.

## Arquitetura

```mermaid
flowchart LR
    Browser[React / Nginx] --> API[FastAPI]
    API --> PG[(PostgreSQL)]
    Worker[Worker de entregas] --> PG
    API -->|evento + regra em uma transação| PG
    Worker -->|resultado fictício| PG
```

1. `POST /api/v1/events` grava um evento único e uma entrega pendente na mesma transação. Falhas são agrupadas por integração e código de erro.
2. A terceira falha ainda sem incidente em uma janela inclusiva de 30 minutos abre um incidente. Falhas equivalentes posteriores atualizam o incidente aberto. Eventos de sucesso são registrados e não encerram incidentes.
3. O worker busca entregas vencidas, registra cada tentativa e aplica intervalos progressivos de `base * 2^(tentativa - 1)` segundos. O destino fictício falha nas primeiras `simulated_failures` tentativas do ciclo inicial.
4. O operador consulta linha do tempo e tentativas, reprocessa uma entrega pendente ou esgotada e encerra o incidente com resolução explícita.

## Roteiro de demonstração

1. Abra http://localhost:8080. Em **Gerar eventos fictícios**, mantenha **3 falhas simuladas na entrega** e clique **Enviar três falhas**.
2. Selecione o incidente aberto. Veja as três falhas em ordem cronológica. Clique **Reenviar duplicata** e confirme que a contagem permanece três.
3. Clique **Atualizar detalhes** após alguns segundos. Cada entrega terá até três tentativas falhas e status **Esgotada**.
4. Clique **Reprocessar** em uma entrega esgotada. A ação simula a recuperação do destino; clique **Atualizar detalhes** para ver a nova tentativa concluída. O histórico dos ciclos anteriores permanece.
5. Descreva uma resolução e clique **Registrar e encerrar**. O incidente aparece como encerrado.

Todos os nomes e eventos gerados pelo painel são fictícios.

## Variáveis de ambiente

Veja `.env.example`. `POSTGRES_DB`, `POSTGRES_USER` e `POSTGRES_PASSWORD` são usados pelo Compose. `DATABASE_URL` configura a API fora do Compose; dentro dele, a URL é construída com as variáveis PostgreSQL. `DELIVERY_MAX_ATTEMPTS` (padrão 3) e `DELIVERY_BASE_DELAY_SECONDS` (padrão 5) controlam o worker. `AI_API_URL`, `AI_API_KEY` e `AI_MODEL` são inteiramente opcionais; sem os três valores, apenas a rota de IA retorna 503. Não coloque credenciais reais no repositório.

Para aplicar migrações manualmente com `DATABASE_URL` configurado: `python -m app.migrate`. Os arquivos em `migrations/` são aplicados em ordem e registrados em `schema_migrations`; versões já aplicadas não são repetidas. O serviço `migrate` no Compose faz isso antes de iniciar API e worker.

## Contratos HTTP principais

### Registrar evento

```bash
curl -X POST http://localhost:8000/api/v1/events -H 'Content-Type: application/json' -d '{"event_id":"demo-001","integration":"demo-crm","status":"failure","error_code":"DEMO_TIMEOUT","message":"Destino fictício indisponível","occurred_at":"2026-11-25T12:00:00Z","simulated_failures":3}'
```

Resposta 202: `{"duplicate":false,"action":"event_recorded","event_id":"demo-001","incident":null}`. Na terceira falha equivalente, `action` é `incident_opened` e `incident` contém o incidente. Reenviar o mesmo `event_id` responde 202 com `duplicate:true` e `action:"duplicate_ignored"`, sem criar nova entrega.

### Consultar e encerrar

```text
GET   /api/v1/incidents?status=open&integration=demo-crm&error_code=DEMO_TIMEOUT&limit=20&offset=0
GET   /api/v1/incidents/counts
GET   /api/v1/incidents/{id}
GET   /api/v1/incidents/{id}/events?limit=100&offset=0
GET   /api/v1/incidents/{id}/deliveries?limit=100&offset=0
GET   /api/v1/deliveries/{id}/attempts?limit=100&offset=0
POST  /api/v1/deliveries/{id}/reprocess
PATCH /api/v1/incidents/{id}/close
POST  /api/v1/incidents/{id}/ai-analysis
```

Exemplo de encerramento: `curl -X PATCH http://localhost:8000/api/v1/incidents/1/close -H 'Content-Type: application/json' -d '{"resolution":"Falha fictícia investigada e entrega reprocessada."}'`. A resposta é o incidente atualizado, com `status:"closed"`, `closed_at` e `resolution`. Filtros inválidos e payloads inválidos retornam 422; recursos inexistentes retornam 404; reprocessamento em estado não permitido retorna 409. Listagens usam `limit` e `offset`.

## Concorrência, idempotência e interrupções

`events.event_id` tem restrição única. Duas requisições simultâneas com o mesmo ID resultam previsivelmente em uma criação e uma duplicata 202. O lock transacional por par integração/código serializa as decisões sobre abertura do incidente. Evento, entrega e alteração do incidente fazem commit juntos. Uma colisão de hash do lock apenas serializa pares adicionais.

O worker usa `FOR UPDATE SKIP LOCKED` para escolher uma entrega por vez, inclusive com múltiplos workers. Tentativa e atualização da entrega são gravadas em uma transação. O estado `running` e o lease existem para recuperação, mas a simulação é instantânea; portanto a interface normalmente mostra `pending`, `succeeded` ou `exhausted`. Se o processo cair antes do commit, a transação é revertida e a entrega pendente será tentada novamente. Se cair após o commit, o resultado já está persistido. O destino fictício não tem efeitos externos. Esta garantia **não** equivaleria a entrega exatamente uma vez em um destino real; tal integração exigiria chave de idempotência no destinatário e tratamento de confirmação ambígua.

O reprocessamento manual incrementa o ciclo, preserva tentativas anteriores, zera o contador do novo ciclo e remove a falha simulada. É permitido para entregas `pending` ou `exhausted`, com lock de linha; `running` e `succeeded` retornam 409. A demonstração não inclui autenticação e deve ser executada localmente.

## Testes e desenvolvimento

Backend: Python 3.11+, PostgreSQL e `python -m pip install -e ".[dev]"`. Os testes criam e removem bancos de teste isolados. Configure `TEST_DATABASE_ADMIN_URL` apontando para um usuário que possa criar bancos; exemplo: `postgresql://incident:local-ci-only@localhost:5432/postgres`.

```bash
ruff check .
pytest
```

Frontend: Node 24+.

```bash
cd frontend
npm ci
npm run lint
npm test
npm run build
```

O GitHub Actions executa lint e testes do backend contra PostgreSQL, além de lint, testes e build do frontend. A IA permanece isolada em `app/ai.py`: a rota opcional usa um provedor compatível com Chat Completions, com dados fictícios e aviso de revisão humana.
