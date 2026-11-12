# Facts — frontend web

Vite + React 19 + TypeScript (strict) + Tailwind 4. Pages (routage par fragment, sans configuration d'hébergeur) :

- `#/check` : Vérificateur IA ;
- `#/arena` : liste des salons publics, recherche par nom ou ID, création d'un salon (public ou privé) ;
- `#/arena/<id>` : un salon en direct (WebSocket), avec saisie des arguments, score de fiabilité et, pour un salon privé, saisie du code d'accès.

Identité : un jeton aléatoire est généré par le navigateur (`localStorage`) et envoyé en premier message du WebSocket ; le serveur n'en garde qu'une empreinte. Le code d'un salon privé est gardé le temps de l'onglet (`sessionStorage`), jamais dans l'URL.

## Développement

```bash
cd frontend
cp .env.example .env        # VITE_API_URL=http://localhost:8000
npm ci
npm run dev                 # http://localhost:5173
```

Le backend doit tourner en parallèle (voir `../backend/README.md`) avec `FACTS_CORS_ORIGINS` incluant `http://localhost:5173`.

## Tests

```bash
npx tsc --noEmit
npx vitest run
```

Les tests couvrent le client HTTP, la reconnexion WebSocket, le reducer des salons, les composants, les pages, la neutralisation des liens (`http/https` uniquement) et la génération de la CSP.

## Build et déploiement (Cloudflare Pages, gratuit)

```bash
VITE_API_URL=https://votre-api.example.com npm run build
```

Le build génère `dist/_headers` (CSP stricte, `connect-src` limité à l'URL de l'API, `frame-ancestors 'none'`, etc.).

Cloudflare Pages : racine `frontend`, commande `npm run build`, sortie `dist`, variable `VITE_API_URL` = URL publique du backend. Côté backend, ajouter l'URL du site dans `FACTS_CORS_ORIGINS`.

> Sur un hébergeur gratuit qui s'endort, la première requête réveille le serveur (appel `/health` au chargement).

## Salons : historique et invitation

- « Mes salons » : historique local (20 entrées, épinglage, statut « Expiré » via `GET /rooms/status`). Le code d'un salon privé y est gardé **sur cet appareil uniquement**, pour revenir sans le redemander.
- Lien d'invitation `#/arena/<id>?code=<code>` : le code est lu puis retiré de la barre d'adresse.
- Le créateur d'un salon vide peut le supprimer (confirmation en deux temps).
- « Proposer une reformulation » : l'IA suggère une question neutre et un thème ; rien n'est appliqué sans clic sur « Utiliser cette question ».
- Modération : avertissement (1/3, 2/3) et écran d'exclusion avec durée restante ; bouton « Signaler » sur les messages des autres ; un message retiré est remplacé par un texte neutre. Le front affiche uniquement des textes fournis par notre serveur, rendus comme du texte.
- Numéros stables : « Participant N » ne change jamais dans un salon ; « vous » marque mes messages (alignés à droite), « absent » ceux d'un participant déconnecté ; « Signaler » est proposé sur tous les messages des autres.
- Exclusion (PR D) : scores individuels affichés dès 3 messages vérifiés ; le créateur voit « Exclure » sous le seuil ; les spectateurs votent (Exclure / Garder, un seul vote) avec décompte ; « Prendre la place » quand un siège est libre ; écran dédié pour une personne exclue ; seuil réglable (20–40) à la création du salon.
- Dictée vocale (PR G) : bouton « Dicter » (30 s max, décompte, arrêt automatique, annulation). Consentement au premier usage (« votre voix est envoyée à Groq »), le texte transcrit s'ajoute dans le champ pour relecture et n'est jamais envoyé seul. Le bouton n'apparaît que si le navigateur sait enregistrer et si le serveur propose la voix. `Permissions-Policy` : `microphone=(self)`, caméra toujours bloquée.
