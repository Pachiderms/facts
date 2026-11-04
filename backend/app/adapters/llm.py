"""Port + adaptateur LLM.

Un seul adaptateur couvre tous les fournisseurs « compatibles OpenAI » : Groq, Gemini
(endpoint compatible), Ollama en local, etc. Changer de fournisseur = changer
FACTS_LLM_BASE_URL / FACTS_LLM_MODEL / FACTS_LLM_API_KEY, sans toucher au code.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

MAX_RESPONSE_CHARS = 50_000


class LLMError(RuntimeError):
    """Échec de l'appel au LLM (réseau, HTTP, réponse inexploitable)."""


class LLMRateLimitError(LLMError):
    """Quota du fournisseur atteint (HTTP 429). Jamais réessayé automatiquement."""


class LLMProvider(Protocol):
    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1200, temperature: float = 0.0
    ) -> str: ...


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 30.0,
        max_retries: int = 1,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._api_key = api_key
        self._max_retries = max_retries
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._sleep = sleep

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1200, temperature: float = 0.0
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,  # 0 par défaut : on veut de la reproductibilité, pas de la créativité
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        response = await self._post_with_retry(payload, headers)
        return self._extract_content(response)

    async def _post_with_retry(self, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            is_last = attempt == self._max_retries
            try:
                response = await self._client.post(self._url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if is_last:
                    # Pas de détail de l'exception : elle peut contenir l'URL du fournisseur.
                    raise LLMError(f"Fournisseur LLM injoignable ({type(exc).__name__}).") from None
                await self._sleep(0.5 * (attempt + 1))
                continue

            if response.status_code == 429:
                raise LLMRateLimitError("Quota du fournisseur LLM atteint.")
            if response.status_code >= 500:
                if is_last:
                    raise LLMError(f"Erreur du fournisseur LLM (HTTP {response.status_code}).")
                await self._sleep(0.5 * (attempt + 1))
                continue
            if response.status_code >= 400:
                # On n'inclut JAMAIS le corps de la réponse : il peut refléter nos en-têtes ou notre clé.
                raise LLMError(f"Requête LLM refusée (HTTP {response.status_code}).")
            return response
        raise LLMError("Échec LLM.")  # inatteignable, satisfait le typage

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("Réponse du fournisseur LLM au format inattendu.") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Réponse du LLM vide.")
        if len(content) > MAX_RESPONSE_CHARS:
            raise LLMError("Réponse du LLM anormalement longue.")
        return content


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    """Extrait un objet JSON d'une réponse de modèle.

    Les petits modèles ajoutent souvent des ```json ... ``` ou une phrase d'introduction
    malgré la consigne : on les tolère, mais on exige un OBJET (pas une liste ni un scalaire).
    """
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise LLMError("La réponse du LLM n'est pas un objet JSON valide.")
