# Integration Incident Monitor

API em Python para receber eventos fictícios por webhook, detectar falhas repetidas em integrações e acompanhar incidentes. O projeto demonstra **FastAPI, orientação a objetos, SQLite, regras de negócio e testes automatizados**.

> Todos os nomes, mensagens e eventos deste repositório são fictícios.

## Regras da primeira versão

- Cada evento possui um `event_id` único.
- Um evento duplicado é ignorado e não aumenta a contagem de falhas.
- Três falhas da mesma `integration` e do mesmo `error_code`, dentro de 30 minutos, abrem um incidente.
- Uma nova falha equivalente atualiza o incidente que já está aberto.
- O encerramento é explícito e exige o registro de uma resolução.
- Eventos de sucesso são armazenados, mas não encerram incidentes automaticamente.

## Estrutura

```text
app/
├── database.py   # conexão e schema SQLite
├── main.py       # aplicação e rotas FastAPI
├── models.py     # objetos de domínio
├── schemas.py    # contratos de entrada e saída
└── services.py   # IncidentService e regras de negócio
tests/
├── test_incident_service.py  # testes unitários das regras
└── test_routes.py            # testes HTTP com TestClient
```

## Como executar

Requer Python 3.11 ou superior.

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Instale e execute:

```bash
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Documentação interativa:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

## Exemplos de requisição e resposta

### Enviar uma falha

```bash
curl -X POST http://127.0.0.1:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-003",
    "integration": "crm-webhook",
    "status": "failure",
    "error_code": "TIMEOUT",
    "message": "O CRM não respondeu dentro do limite.",
    "occurred_at": "2026-11-24T12:10:00Z"
  }'
```

Na terceira falha equivalente dentro da janela:

```json
{
  "duplicate": false,
  "action": "incident_opened",
  "event_id": "evt-003",
  "incident": {
    "id": 1,
    "integration": "crm-webhook",
    "error_code": "TIMEOUT",
    "title": "Falhas repetidas em crm-webhook: TIMEOUT",
    "status": "open",
    "occurrence_count": 3,
    "first_event_at": "2026-11-24T12:00:00Z",
    "last_event_at": "2026-11-24T12:10:00Z",
    "created_at": "2026-11-24T12:10:01Z",
    "updated_at": "2026-11-24T12:10:01Z",
    "closed_at": null,
    "resolution": null
  }
}
```

### Consultar incidentes abertos

```bash
curl "http://127.0.0.1:8000/api/v1/incidents?status=open"
```

### Encerrar um incidente

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/incidents/1/close \
  -H "Content-Type: application/json" \
  -d '{"resolution": "Timeout ajustado e integração reprocessada."}'
```

## Testes e qualidade

```bash
ruff check .
pytest
```

Os testes cobrem evento duplicado, abertura por falha repetida, atualização, janela de repetição, encerramento e rotas HTTP. O GitHub Actions executa lint e testes a cada `push` e `pull request`.

## Etapa opcional: IA

A rota `POST /api/v1/incidents/{id}/ai-analysis` gera um resumo e sugestões de investigação quando um provedor compatível com Chat Completions está configurado. A API acrescenta sempre um aviso de conferência humana, independentemente da resposta do modelo.

Instale a dependência opcional e configure as variáveis do `.env.example`:

```bash
python -m pip install -e ".[ai]"
```

```env
AI_API_URL=https://api.example.com/v1/chat/completions
AI_API_KEY=replace-with-your-key
AI_MODEL=replace-with-your-model
```

Sem essas três variáveis, o restante da API funciona normalmente e a rota opcional responde `503`. Somente metadados fictícios do incidente são enviados: integração, código de erro, contagem, período e status. Nunca publique uma chave no repositório.

Exemplo de resposta:

```json
{
  "incident_id": 1,
  "summary": "A integração apresentou três timeouts em dez minutos.",
  "suggested_investigation": [
    "Verificar a disponibilidade do sistema de destino.",
    "Conferir os logs da integração no período do incidente."
  ],
  "disclaimer": "Sugestão gerada por IA. Confira as informações antes de executar qualquer ação."
}
```

