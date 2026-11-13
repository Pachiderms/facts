"""Envoi du code de connexion par e-mail. Port + adaptateur Resend (HTTP) + boîte d'envoi pour les tests.

Aucune adresse, aucun code ni aucune clé ne figure dans les messages d'erreur ou les journaux.
"""

from dataclasses import dataclass, field
from typing import Protocol

import httpx

RESEND_URL = "https://api.resend.com/emails"


class EmailError(RuntimeError):
    """Envoi impossible (réseau, refus du fournisseur). Message générique : jamais d'adresse ni de clé."""


class EmailSender(Protocol):
    async def send_login_code(self, to: str, code: str, ttl_minutes: int) -> None: ...


def render_login_email(code: str, ttl_minutes: int) -> tuple[str, str, str]:
    """(objet, texte, html). Le code ne contient que des chiffres : rien à échapper."""
    subject = "Votre code de connexion CaFaitDebat"
    text = (
        f"Votre code de connexion CaFaitDebat : {code}\n\n"
        f"Il est valable {ttl_minutes} minutes et ne sert qu'une fois.\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : personne ne peut se connecter sans ce code."
    )
    html = (
        '<div style="font-family:system-ui,sans-serif;max-width:420px;margin:auto;color:#171717">'
        '<p style="font-size:14px">Votre code de connexion <strong>CaFaitDebat</strong> :</p>'
        f'<p style="font-size:32px;font-weight:800;letter-spacing:6px;font-family:ui-monospace,monospace;margin:12px 0">{code}</p>'
        f'<p style="font-size:12px;color:#525252">Il est valable {ttl_minutes} minutes et ne sert qu\'une fois.<br>'
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.</p></div>"
    )
    return subject, text, html


class ResendSender:
    def __init__(self, api_key: str, sender: str, *, timeout_seconds: float = 10.0, client: httpx.AsyncClient | None = None) -> None:
        self._key, self._from, self._timeout, self._client = api_key, sender, timeout_seconds, client

    async def send_login_code(self, to: str, code: str, ttl_minutes: int) -> None:
        subject, text, html = render_login_email(code, ttl_minutes)
        payload = {"from": self._from, "to": [to], "subject": subject, "text": text, "html": html}
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        try:
            if self._client is not None:
                response = await self._client.post(RESEND_URL, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(RESEND_URL, json=payload, headers=headers, timeout=self._timeout)
        except httpx.HTTPError:
            raise EmailError("envoi impossible") from None  # le message d'origine peut contenir l'adresse
        if response.status_code >= 300:
            raise EmailError(f"envoi refusé (HTTP {response.status_code})")


@dataclass
class OutboxSender:
    """Pour les tests et le développement : garde les messages en mémoire au lieu de les envoyer."""

    sent: list[tuple[str, str]] = field(default_factory=list)  # (adresse, code)
    fail: bool = False

    async def send_login_code(self, to: str, code: str, ttl_minutes: int) -> None:
        if self.fail:
            raise EmailError("envoi impossible")
        self.sent.append((to, code))
