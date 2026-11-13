"""Abonnement Pro : état, lien de paiement, webhook du prestataire.

Interrupteur : tant que `FACTS_PAYMENTS_ENABLED` est faux, rien n'est proposé (lien refusé) et le webhook refuse tout.
Le webhook n'a pas de session : seule la signature HMAC du corps brut l'authentifie. Il ne fait jamais confiance à
une valeur du corps avant d'avoir vérifié cette signature.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.adapters import lemonsqueezy
from app.api.deps import enforce_read_rate_limit, optional_user

logger = logging.getLogger("facts.billing")
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _enabled(request: Request) -> bool:
    return request.app.state.settings.payments_enabled and getattr(request.app.state, "billing", None) is not None


@router.get("", dependencies=[Depends(enforce_read_rate_limit)])
async def billing_state(request: Request) -> dict:
    """Disponibilité du paiement et abonnement du compte connecté (jamais de détail sans session valide)."""
    settings = request.app.state.settings
    data: dict = {
        "enabled": _enabled(request),
        "price_label": settings.pro_price_label if _enabled(request) else "",
        "plan": "free",
        "status": None,
        "current_period_end": None,
        "portal_url": None,
    }
    user = await optional_user(request)
    if user is not None and getattr(request.app.state, "billing", None) is not None:
        try:
            info = await request.app.state.billing.status(user.id)
        except Exception:
            return data
        data.update(
            plan="pro" if info["active"] else "free",
            status=info["status"],
            current_period_end=info["current_period_end"],
            portal_url=info["portal_url"],
        )
    return data


@router.post("/checkout", dependencies=[Depends(enforce_read_rate_limit)])
async def checkout(request: Request) -> dict:
    """Lien de paiement pour le compte connecté (un compte est nécessaire : l'abonnement lui est rattaché)."""
    if not _enabled(request):
        raise HTTPException(status_code=503, detail="Le paiement n'est pas encore disponible.")
    user = await optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Connectez-vous pour vous abonner.")
    if (await request.app.state.billing.status(user.id))["active"]:
        raise HTTPException(status_code=409, detail="Vous êtes déjà abonné.")
    settings = request.app.state.settings
    return {"url": lemonsqueezy.checkout_link(settings.lemonsqueezy_checkout_url, user.id, user.email)}


@router.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    if not _enabled(request):
        raise HTTPException(status_code=503, detail="Paiement désactivé.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > lemonsqueezy.MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Corps trop volumineux.")
    raw = b""
    async for chunk in request.stream():  # lecture bornée : un corps sans Content-Length honnête ne gonfle pas la mémoire
        raw += chunk
        if len(raw) > lemonsqueezy.MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Corps trop volumineux.")
    secret = request.app.state.settings.lemonsqueezy_webhook_secret.get_secret_value()
    if not lemonsqueezy.verify_signature(raw, request.headers.get("x-signature"), secret):
        logger.warning("webhook refusé : signature invalide")
        raise HTTPException(status_code=401, detail="Signature invalide.")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON invalide.") from None
    event = lemonsqueezy.parse_subscription_event(payload)
    if event is None:  # évènement qui ne concerne pas un abonnement : accusé de réception, sans effet
        return JSONResponse({"result": "ignored"})
    result = await request.app.state.billing.apply(lemonsqueezy.body_fingerprint(raw), event)
    logger.info("webhook abonnement : %s", result)
    return JSONResponse({"result": result})
