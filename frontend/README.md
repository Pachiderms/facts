# Facts — frontend web

Vite + React 19 + TypeScript (strict) + Tailwind 4. Deux pages : **Vérificateur IA** (`#/check`) et **Arène de débat** (`#/arena`, temps réel via WebSocket).

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
