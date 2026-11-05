"""Configuration centralisée, lue depuis l'environnement (préfixe FACTS_).

Aucun secret n'est codé en dur : la clé LLM vient de FACTS_LLM_API_KEY.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FACTS_", extra="ignore")

    env: str = "dev"
    # Liste séparée par des virgules (évite le parsing JSON de pydantic-settings).
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    # Ne faire confiance à X-Forwarded-For que derrière un proxy maîtrisé.
    trust_proxy_headers: bool = False

    # Limites d'entrée
    assertion_min_chars: int = 10
    assertion_max_chars: int = 500

    # Taille maximale du corps d'une requête HTTP (octets)
    max_body_bytes: int = 8192

    # Rate limiting (par IP)
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    # Recherche web : chaîne de repli, dans l'ordre. Tavily est ignoré si sa clé est absente.
    search_providers: str = "tavily,wikipedia,duckduckgo"
    search_max_results: int = 5
    search_timeout_seconds: float = 8.0
    search_breaker_failures: int = 3  # échecs consécutifs avant d'ignorer un fournisseur
    search_breaker_cooldown_seconds: float = 120.0
    tavily_api_key: str = ""
    # Offre gratuite : 1 000 crédits/mois ; marge car une vérification lance jusqu'à 2 recherches.
    tavily_monthly_limit: int = 900
    wikipedia_lang: str = "fr"

    # Cache des vérifications (24 h : une même assertion ne coûte qu'une recherche par jour)
    cache_ttl_seconds: int = 86_400
    cache_max_entries: int = 500

    # Plafonds par visiteur et par jour (protègent les crédits de recherche et les quotas LLM)
    daily_check_limit: int = 30
    daily_ws_message_limit: int = 200

    # LLM (API compatible OpenAI)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_timeout_seconds: float = 30.0

    # Débats en direct (WebSocket)
    ws_max_message_chars: int = 500  # aligné sur assertion_max_chars : un message est vérifié comme une assertion
    ws_messages_per_minute: int = 12
    ws_max_connections_per_ip: int = 5
    ws_max_room_connections: int = 100
    ws_max_concurrent_checks: int = 2  # protège les quotas gratuits (recherche + LLM)
    ws_max_pending_checks: int = 20
    ws_check_timeout_seconds: float = 60.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
