# Déploiement à 0 € : Render (API) + Cloudflare Pages (site)

Deux services gratuits, sans carte bancaire exigée pour l'usage décrit ici. Les limites ci-dessous sont celles annoncées par les fournisseurs au 9 novembre 2026 ; à revérifier avant de compter dessus.

## Limites à connaître

| Service | Offre gratuite | Conséquence pour Facts |
|---|---|---|
| Render (API) | 1 instance, **mise en veille après 15 min sans trafic** (réveil ≈ 1 min), 750 h/mois, disque éphémère | Les salons vivent en mémoire : **une mise en veille ou un redémarrage les efface**. Les messages WebSocket comptent comme du trafic, donc un salon actif garde l'API éveillée. |
| Cloudflare Pages (site) | 500 builds/mois, 20 000 fichiers, pas de limite de bande passante annoncée | Largement suffisant. |

Garde-fous déjà dans le code : 50 salons maximum, 3 créations par jour et par personne, quotas LLM/recherche, CORS et WebSocket limités à l'adresse du site.

## Ordre à suivre (l'API d'abord, car le site a besoin de son adresse)

### 1. Clés (gratuites)
- **Groq** (LLM) : créer une clé sur console.groq.com. Obligatoire : l'API refuse de démarrer sans clé.
- **Tavily** (recherche, optionnelle) : 1 000 crédits/mois. Sans clé, l'API utilise Wikipédia puis DuckDuckGo.

### 2. API sur Render
1. Render → **New → Blueprint** → choisir le dépôt `Pachiderms/facts` : `render.yaml` crée le service `facts-api`.
2. Saisir les trois variables « à renseigner » : `FACTS_LLM_API_KEY`, `FACTS_TAVILY_API_KEY` (peut rester vide), `FACTS_CORS_ORIGINS` (laisser vide pour l'instant, voir l'étape 4).
3. Une fois déployé, noter l'adresse, par exemple `https://facts-api.onrender.com`. Vérifier : `https://facts-api.onrender.com/health` répond `{"status":"ok"}`.

### 3. Site sur Cloudflare Pages
1. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git** → dépôt `Pachiderms/facts`.
2. Réglages : *Root directory* `frontend` · *Build command* `npm run build` · *Build output directory* `dist`.
3. Variable d'environnement du build : `VITE_API_URL` = l'adresse de l'API (sans slash final). Elle sert aussi à générer la politique de sécurité (CSP) : sans elle, le build échoue volontairement.
4. Noter l'adresse du site, par exemple `https://facts.pages.dev`.

### 4. Relier les deux
Dans Render, définir `FACTS_CORS_ORIGINS` = l'adresse **exacte** du site (`https://facts.pages.dev`, sans slash final ni chemin), puis redéployer. Sans cela, le navigateur bloque les appels et les WebSockets (c'est voulu : aucun autre site ne peut utiliser votre API).

### 5. Vérifier
- Le site s'ouvre, la liste des salons s'affiche (le premier chargement peut prendre ~1 min si l'API dormait).
- Une vérification d'affirmation renvoie un verdict.
- Deux onglets dans un même salon : les messages arrivent en direct.

## Pannes courantes
- **« Failed to fetch » / salons qui ne chargent pas** : `FACTS_CORS_ORIGINS` ne correspond pas exactement à l'adresse du site.
- **L'API ne démarre pas** : `FACTS_LLM_API_KEY` manquante (le journal Render le dit).
- **Build du site en échec** : `VITE_API_URL` absente.
- **Salons disparus** : l'API s'est mise en veille ou a redémarré (limite de l'offre gratuite).
