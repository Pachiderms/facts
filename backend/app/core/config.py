"""Configuration centralisée, lue depuis l'environnement (préfixe FACTS_).

Aucun secret n'est codé en dur : la clé LLM vient de FACTS_LLM_API_KEY.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FACTS_", extra="ignore")

    env: str = "dev"
    # Liste séparée par des virgules (évite le parsing JSON de pydantic-settings).
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    # Ne faire confiance à X-Forwarded-For que derrière un proxy maîtrisé.
    trust_proxy_headers: bool = False
    # Adresses de proxys ajoutées APRÈS celle du client dans X-Forwarded-For (Render : 1). Voir /health/ip.
    proxy_hops: int = Field(default=0, ge=0, le=5)

    # Base de données PostgreSQL (Neon, Supabase…). Vide = tout reste en mémoire, comme avant. SecretStr : jamais
    # affichée dans un journal, un repr ou une trace (l'adresse contient le mot de passe).
    database_url: SecretStr = SecretStr("")
    db_pool_size: int = 3
    db_max_overflow: int = 2

    # Comptes (optionnels). Actifs si la base ET l'identifiant client Google sont renseignés (identifiant PUBLIC).
    google_client_id: str = ""
    session_ttl_days: int = 30
    max_sessions_per_user: int = 10
    google_max_token_age_seconds: int = 600
    login_attempts_per_window: int = 10  # par IP
    login_window_seconds: int = 600

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
    daily_check_limit: int = 30  # visiteur sans compte, par IP
    account_daily_check_limit: int = 60  # compte gratuit, par compte (l'IP garde un plafond large : daily_check_limit x 4)
    pro_daily_check_limit: int = 250  # abonné Pro, par compte
    pro_debate_daily_checks: int = 400  # abonné Pro, par compte (le budget global du débat reste commun à tous)
    daily_ws_message_limit: int = 200
    # Messages de débat qui déclenchent une vérification (appel LLM + recherche), par jour UTC.
    debate_daily_checks: int = 40  # sans compte, par IP
    account_debate_daily_checks: int = 120  # compte gratuit, par compte
    debate_global_daily_checks: int = 300  # tous salons : le reste du plafond d'appels LLM est réservé au chatbot
    # Paiement (Lemon Squeezy, marchand de référence : il gère la TVA). DÉSACTIVÉ tant que payments_enabled est faux :
    # aucun paiement n'est proposé et le webhook refuse tout. À activer après la création de la micro-entreprise.
    payments_enabled: bool = False
    lemonsqueezy_webhook_secret: SecretStr = SecretStr("")  # secret de signature du webhook (min. 16 caractères)
    lemonsqueezy_checkout_url: str = ""  # lien de paiement du produit Pro (https://<boutique>.lemonsqueezy.com/checkout/buy/<id>)
    pro_price_label: str = ""  # libellé affiché, ex. « 5 € / mois » (le prix réel est fixé chez le prestataire)
    billing_grace_days: int = 3  # tolérance après la fin de période (retard de paiement) avant de repasser en gratuit

    # Sel des empreintes de quotas (IP jamais stockées en clair). DOIT être fixe en production avec une base :
    # vide = sel aléatoire à chaque démarrage (quotas durables inopérants).
    quota_salt: str = ""

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
    # Modèle de secours (vide = aucun) : autre modèle donc autre quota. Même fournisseur et même clé par défaut.
    llm_fallback_model: str = ""
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_reasoning_effort: str = ""
    # Plafond global d'appels au modèle principal par 24 h glissantes (Groq gratuit : 1 000/jour). 0 = pas de plafond.
    llm_global_daily_calls: int = 900
    llm_primary_cooldown_seconds: float = 60.0

    # Versioning : « beta » (gratuit, sert à MESURER) ou « v1 » (fournisseurs au crédit). Étiquette chaque ligne de coût.
    profile: Literal["beta", "v1"] = "beta"
    # Mesure des coûts. Endpoint /api/v1/admin/costs fermé (404) sans jeton ; jeton long et aléatoire obligatoire.
    admin_token: SecretStr = SecretStr("")
    cost_flush_seconds: float = 60.0
    # Tarifs en euros, JSON : {"llm": {"modèle": [€ par million de jetons en entrée, en sortie]}, "search": {"tavily": € par crédit}}
    cost_prices: str = ""

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
    ws_max_room_connections: int = 300  # plafond technique absolu, par salon (les plafonds par plan sont dessous)
    ws_max_connections_per_ip_edu: int = 300  # salon Edu : une classe entière partage l'IP de l'établissement
    ws_max_concurrent_checks: int = 2  # protège les quotas gratuits (recherche + LLM)
    ws_max_pending_checks: int = 20
    ws_check_timeout_seconds: float = 60.0
    ws_hello_timeout_seconds: float = 5.0  # délai pour envoyer le premier message (identité + code)

    # Création de salons (mémoire bornée : tout vit en RAM sur l'offre gratuite)
    max_rooms: int = 50
    room_idle_ttl_seconds: int = 1_800  # un salon non permanent, vide et inactif est supprimé
    daily_room_creation_limit: int = 3  # par visiteur et par jour
    # Personnes connectées en même temps dans un salon (intervenants + spectateurs), selon le plan de son CRÉATEUR.
    room_capacity_anonymous: int = 8
    room_capacity_free: int = 8
    room_capacity_pro: int = 20
    room_capacity_edu: int = 300
    # Plan Edu : budget de vérifications d'un salon (plafond par séance) et pool mensuel de la licence (partagé entre ses salons).
    edu_room_check_budget: int = 300
    edu_monthly_check_pool: int = 5_000
    moderation_ban_seconds: int = 3600  # exclusion au 3e message illégal
    moderation_strike_ttl_seconds: int = 86_400  # les avertissements s'oublient après 24 h sans récidive
    moderation_timeout_seconds: float = 10.0
    daily_report_review_limit: int = 20  # signalements jugés par le LLM, par identité et par jour
    daily_reformulation_limit: int = 10  # appels LLM de reformulation, par visiteur et par jour
    room_title_min_chars: int = 10
    room_title_max_chars: int = 120
    room_code_max_failures: int = 5  # codes faux tolérés ...
    room_code_window_seconds: int = 600  # ... par IP sur cette fenêtre (anti-force brute)

    @model_validator(mode="after")
    def _admin_and_prices_are_sound(self) -> "Settings":
        token = self.admin_token.get_secret_value()
        if token and len(token) < 32:
            raise ValueError("FACTS_ADMIN_TOKEN : 32 caractères minimum (ex. `openssl rand -hex 32`)")
        parse_prices(self.cost_prices)  # refuse un JSON invalide au démarrage plutôt que des coûts faux en silence
        return self

    @model_validator(mode="after")
    def _payments_need_a_complete_setup(self) -> "Settings":
        # Activer le paiement avec une configuration incomplète : refus au démarrage, pas une panne silencieuse.
        if self.payments_enabled:
            if len(self.lemonsqueezy_webhook_secret.get_secret_value()) < 16:
                raise ValueError("FACTS_PAYMENTS_ENABLED exige FACTS_LEMONSQUEEZY_WEBHOOK_SECRET (16 caractères minimum)")
            if not self.lemonsqueezy_checkout_url.startswith("https://"):
                raise ValueError("FACTS_PAYMENTS_ENABLED exige FACTS_LEMONSQUEEZY_CHECKOUT_URL en https://")
            if not self.accounts_available:
                raise ValueError("FACTS_PAYMENTS_ENABLED exige les comptes (base de données + FACTS_GOOGLE_CLIENT_ID)")
        return self

    @property
    def stt_key(self) -> str:
        return self.stt_api_key or self.llm_api_key

    @property
    def accounts_available(self) -> bool:
        return bool(self.google_client_id.strip()) and bool(self.database_url.get_secret_value())

    @property
    def voice_available(self) -> bool:
        return self.stt_enabled and bool(self.stt_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def parse_prices(raw: str) -> dict[str, dict[str, list[float]]]:
    """Tarifs normalisés : {"llm": {modèle: [entrée, sortie]}, "search": {moteur: [par crédit]}}. Vide = aucun tarif."""
    import json
    import math

    if not raw.strip():
        return {"llm": {}, "search": {}}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("FACTS_COST_PRICES : JSON invalide") from None
    if not isinstance(data, dict) or set(data) - {"llm", "search"}:
        raise ValueError('FACTS_COST_PRICES : clés autorisées « llm » et « search »')

    def number(v: object) -> float:
        if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or v < 0:
            raise ValueError("FACTS_COST_PRICES : les prix sont des nombres positifs ou nuls")
        return float(v)

    out: dict[str, dict[str, list[float]]] = {"llm": {}, "search": {}}
    for model, pair in (data.get("llm") or {}).items():
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("FACTS_COST_PRICES : « llm » attend [entrée, sortie] par modèle")
        out["llm"][str(model)] = [number(pair[0]), number(pair[1])]
    for provider, price in (data.get("search") or {}).items():
        out["search"][str(provider)] = [number(price)]
    return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
