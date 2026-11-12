"""Configuration centralisée, lue depuis l'environnement (préfixe FACTS_).

Aucun secret n'est codé en dur : la clé LLM vient de FACTS_LLM_API_KEY.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FACTS_", extra="ignore")

    env: str = "dev"
    # Liste séparée par des virgules (évite le parsing JSON de pydantic-settings).
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    # Ne faire confiance à X-Forwarded-For que derrière un proxy maîtrisé.
    trust_proxy_headers: bool = False

    # Base de données PostgreSQL (Neon, Supabase…). Vide = tout reste en mémoire, comme avant. SecretStr : jamais
    # affichée dans un journal, un repr ou une trace (l'adresse contient le mot de passe).
    database_url: SecretStr = SecretStr("")
    db_pool_size: int = 3
    db_max_overflow: int = 2

    # Limites d'entrée
    assertion_min_chars: int = 10
    assertion_max_chars: int = 500

    # Taille maximale du corps d'une requête HTTP (octets)
    max_body_bytes: int = 8192

    # Rate limiting (par IP)
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60
    # Lectures légères (liste des salons) : compteur séparé, pour que le rafraîchissement automatique
    # du front ne consomme pas le quota des vérifications.
    read_rate_limit_requests: int = 60

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

    # Tri des messages par le LLM : repère les faits sans chiffre. Coûte un appel LLM par message long sans chiffre ;
    # désactiver (FACTS_CLAIM_TRIAGE=false) pour revenir à la règle gratuite seule.
    claim_triage: bool = True
    claim_triage_timeout_seconds: float = 10.0

    # LLM (API compatible OpenAI)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile est retiré chez Groq depuis le 16/08/2026
    llm_reasoning_effort: str = ""  # "low" recommandé avec les modèles gpt-oss ; vide = non envoyé
    llm_timeout_seconds: float = 30.0

    # Saisie vocale (Groq Whisper). Désactivée sans clé. Offre gratuite Groq : ~28 800 s d'audio par jour.
    stt_enabled: bool = True
    stt_base_url: str = "https://api.groq.com/openai/v1"
    stt_api_key: str = ""  # vide = réutilise llm_api_key (même compte Groq)
    stt_model: str = "whisper-large-v3-turbo"
    stt_timeout_seconds: float = 20.0
    stt_max_bytes: int = 1_000_000  # 30 s d'audio compressé tiennent dans ~250 Ko ; marge x4
    stt_max_seconds: float = 30.0
    stt_daily_per_person: int = 20
    stt_daily_per_ip: int = 60  # plafond large : plusieurs personnes peuvent partager une IP
    stt_per_minute: int = 6
    stt_global_daily_seconds: int = 20_000  # reste sous les 28 800 s/jour de Groq

    # Débats en direct (WebSocket)
    ws_max_message_chars: int = 500  # aligné sur assertion_max_chars : un message est vérifié comme une assertion
    ws_messages_per_minute: int = 12
    ws_max_connections_per_ip: int = 5
    ws_max_room_connections: int = 100
    ws_max_concurrent_checks: int = 2  # protège les quotas gratuits (recherche + LLM)
    ws_max_pending_checks: int = 20
    ws_check_timeout_seconds: float = 60.0
    ws_hello_timeout_seconds: float = 5.0  # délai pour envoyer le premier message (identité + code)

    # Création de salons (mémoire bornée : tout vit en RAM sur l'offre gratuite)
    max_rooms: int = 50
    room_idle_ttl_seconds: int = 1_800  # un salon non permanent, vide et inactif est supprimé
    daily_room_creation_limit: int = 3  # par visiteur et par jour
    moderation_ban_seconds: int = 3600  # exclusion au 3e message illégal
    moderation_strike_ttl_seconds: int = 86_400  # les avertissements s'oublient après 24 h sans récidive
    moderation_timeout_seconds: float = 10.0
    daily_report_review_limit: int = 20  # signalements jugés par le LLM, par identité et par jour
    daily_reformulation_limit: int = 10  # appels LLM de reformulation, par visiteur et par jour
    room_title_min_chars: int = 10
    room_title_max_chars: int = 120
    room_code_max_failures: int = 5  # codes faux tolérés ...
    room_code_window_seconds: int = 600  # ... par IP sur cette fenêtre (anti-force brute)

    @property
    def stt_key(self) -> str:
        return self.stt_api_key or self.llm_api_key

    @property
    def voice_available(self) -> bool:
        return self.stt_enabled and bool(self.stt_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
