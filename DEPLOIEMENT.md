# Déploiement à 0 € : Render (API) + Cloudflare (site)

Deux services gratuits, sans carte bancaire exigée pour l'usage décrit ici. Les limites ci-dessous sont celles annoncées par les fournisseurs au 9 novembre 2026 ; à revérifier avant de compter dessus.

## Limites à connaître

| Service | Offre gratuite | Conséquence pour Facts |
|---|---|---|
| Render (API) | 1 instance, **mise en veille après 15 min sans trafic** (réveil ≈ 1 min), 750 h/mois, disque éphémère | Les salons vivent en mémoire : **une mise en veille ou un redémarrage les efface**. Les messages WebSocket comptent comme du trafic, donc un salon actif garde l'API éveillée. |
| Cloudflare (site) | Hébergement statique gratuit, pas de mise en veille ; Pages : 500 builds/mois, 20 000 fichiers | Largement suffisant. |

Garde-fous déjà dans le code : 50 salons maximum, 3 créations par jour et par personne, quotas LLM/recherche, CORS et WebSocket limités à l'adresse du site.

## Ordre à suivre (l'API d'abord, car le site a besoin de son adresse)

### 1. Clés (gratuites)
- **Groq** (LLM) : créer une clé sur console.groq.com. Obligatoire : l'API refuse de démarrer sans clé.
- **Tavily** (recherche, optionnelle) : 1 000 crédits/mois. Sans clé, l'API utilise Wikipédia puis DuckDuckGo.

### 2. API sur Render
1. Render → **New → Blueprint** → choisir le dépôt `Pachiderms/facts` : `render.yaml` crée le service `facts-api`.
2. Saisir les trois variables « à renseigner » : `FACTS_LLM_API_KEY`, `FACTS_TAVILY_API_KEY` (peut rester vide), `FACTS_CORS_ORIGINS` (laisser vide pour l'instant, voir l'étape 4).
3. Une fois déployé, noter l'adresse, par exemple `https://facts-api.onrender.com`. Vérifier : `https://facts-api.onrender.com/health` répond `{"status":"ok"}`.

### 3. Site sur Cloudflare
Cloudflare propose aujourd'hui soit **Pages**, soit **Workers** (les deux hébergent le site statique et prennent en charge le fichier d'en-têtes de sécurité généré au build). Le guide a été validé avec un projet **Workers**, dont l'adresse est en `.workers.dev`.
1. Cloudflare → **Workers & Pages → Create → Connect to Git** → dépôt `Pachiderms/facts`.
2. Réglages : *Root directory* `frontend` · *Build command* `npm run build` · *Build output directory* `dist`.
3. Variable du **build** : `VITE_API_URL` = l'adresse de l'API (sans slash final). Elle sert aussi à générer la politique de sécurité (CSP) : sans elle, le build échoue volontairement.
   Avec Workers, elle doit être dans **Settings → Build → Variables and secrets** (variables du build). Celles de la section générale « Variables and secrets » ne valent que pour l'exécution et ne sont pas vues par le build : le site viserait alors `localhost:8000` et afficherait « Serveur injoignable ».
4. Noter l'adresse **Production** du site (`https://….workers.dev` ou `https://….pages.dev`). Pas l'adresse *Preview*, qui change à chaque branche. Pour la copier sans erreur : ouvrir le site, console du navigateur (F12), taper `location.origin`.

### 4. Relier les deux
Dans Render, définir `FACTS_CORS_ORIGINS` = l'adresse **exacte** du site (sans slash final ni chemin ; plusieurs adresses possibles, séparées par des virgules sans espace), puis redéployer. Sans cela, le navigateur bloque les appels et les WebSockets (c'est voulu : aucun autre site ne peut utiliser votre API).

### 5. Vérifier
- Le site s'ouvre, la liste des salons s'affiche (le premier chargement peut prendre ~1 min si l'API dormait).
- Une vérification d'affirmation renvoie un verdict.
- Deux onglets dans un même salon : les messages arrivent en direct.

## Garder l'API éveillée (optionnel, gratuit)

Render met l'API en veille après 15 minutes sans trafic. Un pinger externe l'évite :

1. Créer un compte gratuit sur **UptimeRobot** (uptimerobot.com).
2. **Add New Monitor** → type *HTTP(s)* → URL `https://<votre-api>.onrender.com/health` → intervalle **5 minutes** (le plus court de l'offre gratuite ; le seuil de veille est de 15).
3. Garder l'API comme **seul** service gratuit de votre espace Render : rester éveillée en continu consomme environ 744 h sur les 750 h offertes par mois (mois de 31 jours). À vérifier le premier mois dans le tableau de bord Render.

À éviter : un cron GitHub Actions (exécutions souvent retardées, parfois au-delà de 15 minutes).

Cela ne protège pas des **redémarrages** décidés par Render ni des redéploiements : les salons en mémoire sont alors perdus.

## Repérer les redémarrages

`/health` renvoie le temps écoulé depuis le démarrage :

```json
{"status": "ok", "uptime_seconds": 86412}
```

Dans UptimeRobot, la page de détail du moniteur permet de relire les réponses ; une valeur qui retombe près de 0 indique un redémarrage (donc des salons perdus) à ce moment-là. Rien d'autre n'est exposé par cette route.

## Allumer, éteindre, mettre à jour

| Partie | État normal | Mettre hors ligne | Remettre en ligne |
|---|---|---|---|
| Site (Cloudflare) | Toujours actif, sans veille | Désactiver le toggle `workers.dev` (Domains & Routes) : l'adresse ne répond plus, le code reste intact | Réactiver le toggle |
| API (Render) | Actif ; en veille après 15 min sans trafic, sauf pinger | **Suspend Service** (ne consomme plus d'heures) | **Resume** |
| Pinger (UptimeRobot) | Appelle `/health` toutes les 5 min | Mettre le moniteur en pause | Reprendre |

- **Tout couper** : pinger en pause, puis API suspendue. Le site peut rester allumé (il affichera « Serveur injoignable ») ou être désactivé aussi.
- **Mises à jour** : chaque fusion sur `main` reconstruit le site (Cloudflare) et redéploie l'API (Render), automatiquement. Le redéploiement de l'API redémarre le service : **les salons en mémoire sont perdus**, donc éviter de fusionner pendant un débat.
- **Changements d'adresse** : nouvelle adresse du site → mettre à jour `FACTS_CORS_ORIGINS` (Render). Nouvelle adresse de l'API → mettre à jour `VITE_API_URL` (variables du build Cloudflare) **et relancer un build**, car la valeur est figée à la construction.
- **Secrets** : clés Groq et Tavily uniquement dans Render, jamais dans le dépôt.
- **Surveillance** : logs en direct et état dans Render ; e-mail d'alerte possible via UptimeRobot ; consommation d'heures gratuites à relire le premier mois.

## Pannes courantes
- **« Failed to fetch » / salons qui ne chargent pas** : `FACTS_CORS_ORIGINS` ne correspond pas exactement à l'adresse du site.
- **Console : « CORS header missing »** : `FACTS_CORS_ORIGINS` ne correspond pas exactement à l'adresse du site (voir `location.origin`).
- **« Serveur injoignable » et aucune requête `/api/v1` dans les logs Render** : `VITE_API_URL` absente du build (le site vise `localhost:8000`).
- **« Retry build : No build associated with that uuid »** : lien périmé ; déclencher un nouveau build par un commit sur `main`.
- **L'API ne démarre pas** : `FACTS_LLM_API_KEY` manquante (le journal Render le dit).
- **Build du site en échec** : `VITE_API_URL` absente.
- **Salons disparus** : l'API s'est mise en veille ou a redémarré (limite de l'offre gratuite).
