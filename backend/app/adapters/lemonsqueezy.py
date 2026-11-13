"""Lemon Squeezy (marchand de référence : il facture, collecte et reverse la TVA). Aucune donnée bancaire ne nous parvient.

Ce module est pur (sans réseau ni base) : vérification de la signature d'un webhook, lecture d'un évènement
d'abonnement, construction du lien de paiement. Changer de prestataire = écrire un module équivalent.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import UUID

PROVIDER = "lemonsqueezy"
MAX_BODY_BYTES = 64 * 1024  # un évènement d'abonnement fait quelques ko ; au-delà, c'est un abus
KNOWN_STATUSES = {"on_trial", "active", "paused", "past_due", "unpaid", "cancelled", "expired"}


def verify_signature(raw_body: bytes, signature: str | None, secret: str) -> bool:
    """HMAC-SHA256 hexadécimal du corps BRUT (en-tête X-Signature), comparé en temps constant."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def body_fingerprint(raw_body: bytes) -> str:
    """Identifiant d'évènement : une même livraison rejouée a le même corps, donc la même empreinte."""
    return hashlib.sha256(raw_body).hexdigest()


@dataclass(frozen=True)
class SubscriptionEvent:
    user_id: UUID
    subscription_id: str
    customer_id: str | None
    status: str
    period_end: datetime | None
    portal_url: str | None
    event_at: datetime


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_subscription_event(payload: object) -> SubscriptionEvent | None:
    """Évènement d'abonnement exploitable, ou None (autre type d'évènement, champ manquant ou mal formé).

    Le compte vient de `meta.custom_data.user_id`, posé par NOTRE lien de paiement (voir `checkout_link`).
    """
    if not isinstance(payload, dict):
        return None
    meta, data = payload.get("meta"), payload.get("data")
    if not isinstance(meta, dict) or not isinstance(data, dict) or data.get("type") != "subscriptions":
        return None
    name = meta.get("event_name")
    if not isinstance(name, str) or not name.startswith("subscription_") or name.startswith("subscription_payment_"):
        return None
    attrs = data.get("attributes")
    custom = meta.get("custom_data")
    if not isinstance(attrs, dict) or not isinstance(custom, dict):
        return None
    try:
        user_id = UUID(str(custom.get("user_id")))
    except ValueError:
        return None
    status, sub_id = attrs.get("status"), data.get("id")
    if status not in KNOWN_STATUSES or not isinstance(sub_id, (str, int)) or not str(sub_id).strip() or len(str(sub_id)) > 64:
        return None
    event_at = _parse_time(attrs.get("updated_at"))
    if event_at is None:
        return None
    customer = attrs.get("customer_id")
    urls = attrs.get("urls")
    portal = urls.get("customer_portal") if isinstance(urls, dict) else None
    return SubscriptionEvent(
        user_id=user_id,
        subscription_id=str(sub_id),
        customer_id=str(customer) if isinstance(customer, (str, int)) and len(str(customer)) <= 64 else None,
        status=status,
        period_end=_parse_time(attrs.get("ends_at")) or _parse_time(attrs.get("renews_at")),
        # Lien affiché au client : uniquement du https, longueur bornée (la valeur vient d'un tiers).
        portal_url=portal if isinstance(portal, str) and portal.startswith("https://") and len(portal) <= 512 else None,
        event_at=event_at,
    )


def checkout_link(base_url: str, user_id: UUID, email: str) -> str:
    """Lien de paiement personnalisé : l'adresse est pré-remplie et l'identifiant du compte revient dans le webhook."""
    query = urlencode({"checkout[email]": email, "checkout[custom][user_id]": str(user_id)})
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{query}"
