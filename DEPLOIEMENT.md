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
1. Render → **New → Blueprint** → choisir le dépôt `Pachiderms/facts` : `render.yaml` crée le service `facts-api-eu` (nom propre à ce service ; Render refuse un nom déjà pris dans votre espace, même suspendu).
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

## Déplacer l'API vers une autre région (ex. Oregon → Francfort)

Render ne change pas la région d'un service existant (`render.yaml` fixe `region: frankfurt` à la création). Pour déménager :

1. Dans Render : **New → Blueprint**, choisir ce dépôt : le nouveau service est créé à Francfort. Saisir les variables « à renseigner » (clés Groq/Tavily, `FACTS_CORS_ORIGINS`, éventuellement `FACTS_DATABASE_URL`).
2. Noter la nouvelle adresse de l'API, la mettre dans `VITE_API_URL` (variables du build Cloudflare) **et relancer un build** du site.
3. Vérifier `/health` et un salon, mettre à jour le pinger (UptimeRobot ou `FACTS_API_URL` GitHub) avec la nouvelle adresse.
4. Seulement ensuite : suspendre puis supprimer l'ancien service (sinon il consomme des heures gratuites en doublon).

Rien n'est perdu : les salons sont en mémoire et repartent de zéro à chaque déploiement.

## Base de données Neon (optionnelle, gratuite)

Inutile tant que rien n'est stocké en base (les salons restent en mémoire). À faire avant les comptes utilisateurs.

1. Créer un compte sur **neon.com**, puis un projet (région la plus proche de Render, par ex. Francfort). Offre gratuite : 1 Go par projet, 100 h de calcul par mois, mise en veille après 5 minutes d'inactivité (premier appel plus lent de 1 à 3 s).
2. Dans la console Neon (console.neon.tech), ouvrir le projet puis cliquer sur **Connect** dans la barre de navigation. Laisser Branch/Compute/Database/Role par défaut, vérifier que l'interrupteur **Connection pooling** est activé, puis copier l'adresse (le nom du serveur contient `-pooler`). Région conseillée : la même que Render (Francfort).
3. Dans Render : variable `FACTS_DATABASE_URL` = cette adresse, puis redéployer. Les migrations s'appliquent automatiquement au démarrage ; le journal affiche `Running upgrade  -> 0001`.
4. Vérifier à la main : `https://<votre-api>.onrender.com/health/db` → `{"db":"ok"}`.

**Ne pas donner `/health/db` au pinger** : chaque appel réveille la base et consomme des heures de calcul. `/health` (pinger) ne la touche pas. Pour couper la base : vider `FACTS_DATABASE_URL` et redéployer.

## Connexion avec Google (optionnelle, gratuite)

Nécessite la base Neon (ci-dessus). Sans identifiant Google, le site fonctionne sans comptes.

1. Console Google Cloud (console.cloud.google.com) : créer un projet.
2. **Google Auth Platform** (ou *APIs & Services → OAuth consent screen*) : renseigner le nom de l'application, votre e-mail d'assistance, type d'utilisateurs **externe**. Penser à **publier l'application** (statut « en production ») : en mode test, seuls les comptes de test peuvent se connecter.
3. **Clients** (ou *Credentials → Create credentials → OAuth client ID*) : type **Application Web**. Dans **Origines JavaScript autorisées**, ajouter l'adresse EXACTE du site (`https://xxx.workers.dev`, sans slash final) et, pour tester en local, `http://localhost:5173`. Aucune « URI de redirection » n'est nécessaire.
4. Copier l'**ID client** (`…apps.googleusercontent.com`). C'est une valeur **publique**, pas un secret. Ne cherchez pas de « secret client » : il n'est pas utilisé.
5. Dans Render : `FACTS_GOOGLE_CLIENT_ID` = cet ID, puis redéployer. Le bouton apparaît sur le site (rechargez la page). Vérifier : `https://<votre-api>/api/v1/features` contient `"accounts": true`.

Les changements d'origines côté Google peuvent mettre de 5 minutes à quelques heures à s'appliquer. Erreur `origin_mismatch` : l'adresse saisie ne correspond pas exactement à celle du site. Si Google refuse l'adresse `workers.dev` comme origine, un nom de domaine à vous (environ 10 €/an) réglera le problème.

## Garder l'API éveillée (optionnel, gratuit)

Render met l'API en veille après 15 minutes sans trafic. Un pinger externe l'évite :

1. Créer un compte gratuit sur **UptimeRobot** (uptimerobot.com).
2. **Add New Monitor** → type *HTTP(s)* → URL `https://<votre-api>.onrender.com/health` → intervalle **5 minutes** (le plus court de l'offre gratuite ; le seuil de veille est de 15).
3. Garder l'API comme **seul** service gratuit de votre espace Render : rester éveillée en continu consomme environ 744 h sur les 750 h offertes par mois (mois de 31 jours). À vérifier le premier mois dans le tableau de bord Render.

### Variante GitHub Actions (déjà dans le dépôt, éteinte par défaut)

Le workflow `.github/workflows/keepalive.yml` appelle `/health` toutes les 10 minutes, de 06h à 23h UTC seulement (~530 h/mois d'API éveillée au lieu de 744 h).

- **Allumer** : dans GitHub, *Settings → Secrets and variables → Actions → Variables*, créer `FACTS_API_URL` (ex. `https://facts-api.onrender.com`) et `KEEPALIVE_ENABLED` = `true`.
- **Éteindre (le plus simple)** : mettre `KEEPALIVE_ENABLED` à `false` ou supprimer la variable. Le workflow continue de s'afficher mais ne fait aucun appel, donc ne réveille pas l'API et ne consomme pas d'heures Render. On peut aussi désactiver le workflow dans l'onglet *Actions*.
- **Test manuel** : onglet *Actions → keepalive → Run workflow*.
- **Limites** : GitHub retarde parfois les exécutions planifiées (au-delà de 15 min, l'API peut s'endormir malgré tout) ; il désactive les workflows planifiés après 60 jours sans activité dans le dépôt ; gratuit tant que le dépôt est public. UptimeRobot (ci-dessus) est plus régulier : en utiliser un seul des deux.

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
| Pinger (UptimeRobot ou GitHub Actions) | Appelle `/health` régulièrement | Moniteur en pause, ou `KEEPALIVE_ENABLED=false` | Reprendre, ou `KEEPALIVE_ENABLED=true` |

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


## Quotas : vérifier que l'adresse du visiteur est bien lue (Render)

1. Ouvrir `https://<votre-api>.onrender.com/health/ip` dans le navigateur.
2. `resolved_ip` doit être **votre adresse publique** (comparez avec un site « quelle est mon IP »), et rester identique à chaque rechargement. Sinon, ajustez `FACTS_PROXY_HOPS` (0, 1, 2…) sur Render en regardant `x_forwarded_for` : la bonne valeur est le nombre d'adresses qui suivent la vôtre.
3. Le blueprint crée `FACTS_QUOTA_SALT` automatiquement. Sur un service existant, ajoutez-la à la main (une valeur aléatoire quelconque, **à ne plus changer** : la changer repart de zéro pour tout le monde) et ajoutez `FACTS_PROXY_HOPS=1`.
4. Les compteurs sont dans Neon (migration 0004 appliquée au démarrage) : ils survivent aux veilles et redéploiements.

## Nom de domaine personnalisé (exemple : `cafaitdebat.fr`)

Le site et l'API peuvent garder leurs adresses gratuites ; un domaine à vous les rend plus sûres et plus lisibles. Ordre qui ne casse rien (les anciennes adresses restent actives pendant la transition) :

1. **Acheter** le domaine (OVHcloud, Gandi…). Un particulier peut le faire ; la micro-entreprise sera nécessaire avant d'encaisser des paiements.
2. **Cloudflare** : *Add a domain* (offre Free). Vérifier que les enregistrements existants (MX/TXT de la messagerie incluse) ont été importés. Chez le registrar, remplacer les serveurs de noms par les deux de Cloudflare.
3. **Site** : Worker → *Settings → Domains & Routes → Add → Custom domain* : `domaine.fr` et `www.domaine.fr`.
4. **API** : Render → *Settings → Custom Domains* → `api.domaine.fr`. Dans Cloudflare, `CNAME api` → `<service>.onrender.com`, en **« DNS only » (nuage gris)** : le proxy Cloudflare ajouterait une adresse dans `X-Forwarded-For` et fausserait les quotas par IP.
5. **Render** : `FACTS_CORS_ORIGINS=https://domaine.fr,https://www.domaine.fr` (virgules, sans slash final ; garder l'ancienne adresse le temps de la transition).
6. **Cloudflare, variables de build** : `VITE_API_URL=https://api.domaine.fr`, puis relancer un build (la valeur est figée à la construction ; la CSP en est déduite).
7. **Google Cloud** : *Identifiants → ID client OAuth → Origines JavaScript autorisées* : `https://domaine.fr` et `https://www.domaine.fr`. (Les « domaines autorisés » de l'écran de consentement sont un réglage différent, à renseigner aussi.)
8. **Pinger** : `https://api.domaine.fr/health`.
9. **Vérifier** : `https://api.domaine.fr/health` ; `/health/ip` (`resolved_ip` = votre adresse publique, sinon ajuster `FACTS_PROXY_HOPS`) ; un salon (WebSocket) ; la connexion Google.
10. **Ensuite** : retirer les anciennes origines (`workers.dev`) de CORS et de Google ; activer le DNSSEC dans Cloudflare et recopier l'enregistrement DS chez le registrar.


## Mesurer les coûts réels (bêta → V1)

La bêta sert à savoir **combien coûte vraiment** une vérification avant de fixer un prix. Chaque appel au modèle (jetons en entrée et en sortie) et chaque crédit de recherche est compté, par jour, par type d'action (`check` = vérificateur, `room_check` = message de salon, `moderation`, `triage`, `reformulation`) et par modèle. **Aucune donnée personnelle** n'est stockée : ni identité, ni IP, ni texte. Il faut la base de données (table `cost_usage`, créée par la migration 0006).

1. Sur Render, créer `FACTS_ADMIN_TOKEN` avec une valeur aléatoire de 32 caractères ou plus (`openssl rand -hex 32`). Sans elle, l'endpoint n'existe pas (réponse 404).
2. Renseigner `FACTS_COST_PRICES` avec les tarifs publics de vos fournisseurs, en euros (JSON) :
   `{"llm": {"openai/gpt-oss-120b": [0.15, 0.60]}, "search": {"tavily": 0.008}}`
   (`llm` : prix par million de jetons, [entrée, sortie] ; `search` : prix par crédit). Les prix ne sont pas stockés : corriger un tarif corrige aussi le passé. Les chiffres ci-dessus sont des exemples à remplacer par les tarifs réels.
3. Lire les coûts : `curl -H "Authorization: Bearer <jeton>" "https://api.<votre-domaine>/api/v1/admin/costs?days=7"`. La réponse donne, par action, le coût total et le **coût moyen par action** (`cost_per_action_eur`), ainsi que la liste `unpriced` des modèles utilisés sans tarif (leur coût compte 0 : renseignez-les).
4. `FACTS_PROFILE` vaut `beta` aujourd'hui ; passer à `v1` au moment de basculer sur les offres au crédit sépare les mesures des deux périodes.

Les compteurs sont écrits toutes les 60 secondes et à l'arrêt du serveur ; un redémarrage brutal peut perdre au plus une minute de mesures. Après trois essais de jeton faux depuis une même IP, l'endpoint répond 429.

## Paiement Pro (Lemon Squeezy) : à n'ouvrir qu'avec une micro-entreprise

Le code est livré **éteint** (`FACTS_PAYMENTS_ENABLED=false`) : la page Tarifs affiche « Bientôt disponible », le lien de paiement et le webhook refusent tout. Rien n'est encaissé tant que vous ne l'allumez pas.

**Avant d'allumer**
1. Créer la micro-entreprise (guichet unique des formalités, gratuit) et obtenir le SIRET.
2. Compléter `frontend/src/lib/legal.ts` (nom, adresse, e-mail, SIRET, directeur de la publication). Les champs vides s'affichent « À compléter » sur les pages Mentions légales, Confidentialité et CGU. Faire relire ces textes (ce sont des modèles, pas un avis juridique) et vérifier la région de la base Neon indiquée.
3. Créer la boutique et le produit « Pro » (abonnement mensuel) chez Lemon Squeezy ; le prix se fixe là-bas. Copier le lien de paiement du produit.
4. Dans Lemon Squeezy → Settings → Webhooks : URL `https://api.<votre-domaine>/api/v1/billing/webhook`, un secret de 16 caractères minimum, évènements **subscription_created, subscription_updated, subscription_cancelled, subscription_resumed, subscription_expired, subscription_paused, subscription_unpaused**.
5. Sur Render, renseigner `FACTS_LEMONSQUEEZY_WEBHOOK_SECRET` (le même secret), `FACTS_LEMONSQUEEZY_CHECKOUT_URL`, `FACTS_PRO_PRICE_LABEL` (ex. « 5 € / mois »), puis passer `FACTS_PAYMENTS_ENABLED` à `true`. Le serveur refuse de démarrer si une valeur manque (message explicite dans les journaux).
6. Tester en **mode test** de Lemon Squeezy (carte de test) : le compte doit passer Pro en quelques secondes ; vérifier aussi la résiliation.

**À savoir**
- La base migre seule au démarrage (tables `subscriptions` et `billing_events`).
- Un abonné Pro a des plafonds plus hauts (`FACTS_PRO_DAILY_CHECK_LIMIT`, `FACTS_PRO_DEBATE_DAILY_CHECKS`), mais le budget global du débat et le plafond d'appels LLM restent communs à tous : à surveiller avant de vendre à beaucoup de monde (offre gratuite Groq : ~1 000 appels par jour).
- Supprimer son compte efface l'abonnement côté serveur mais **ne résilie pas** la facturation chez Lemon Squeezy : l'abonné doit d'abord résilier (lien « Gérer mon abonnement »).
- Si Render dort, Lemon Squeezy réessaie le webhook plusieurs fois ; chaque livraison est idempotente.
