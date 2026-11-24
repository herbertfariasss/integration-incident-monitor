from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IncidentAnalysis:
    summary: str
    suggested_investigation: list[str]


class IncidentAssistant(Protocol):
    def analyze(self, incident: dict[str, object]) -> IncidentAnalysis: ...


class OpenAICompatibleIncidentAssistant:
    """Optional adapter for providers that expose a chat-completions-compatible API."""

    def __init__(self, *, api_url: str, api_key: str, model: str) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def analyze(self, incident: dict[str, object]) -> IncidentAnalysis:
        import httpx

        safe_payload = {
            "integration": incident["integration"],
            "error_code": incident["error_code"],
            "occurrence_count": incident["occurrence_count"],
            "first_event_at": incident["first_event_at"],
            "last_event_at": incident["last_event_at"],
            "status": incident["status"],
        }
        prompt = (
            "Analise este incidente fictício de integração. Responda somente em JSON, "
            '{"summary":"...","suggested_investigation":["...","..."]}. '
            "Não invente causa raiz; sugira verificações objetivas. Dados: "
            f"{json.dumps(safe_payload, ensure_ascii=False)}"
        )
        response = httpx.post(
            self.api_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(self._strip_code_fence(content))

        summary = parsed.get("summary")
        suggestions = parsed.get("suggested_investigation")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("O provedor de IA retornou um resumo inválido")
        if not isinstance(suggestions, list) or not all(
            isinstance(item, str) and item.strip() for item in suggestions
        ):
            raise ValueError("O provedor de IA retornou sugestões inválidas")
        return IncidentAnalysis(summary.strip(), [item.strip() for item in suggestions])

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        content = content.strip()
        if not content.startswith("```"):
            return content
        lines = content.splitlines()
        return "\n".join(lines[1:-1]).strip()
