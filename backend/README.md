# Facts : backend

API de vérification de faits (politique / débats). Python 3.12+, FastAPI, coût d'hébergement visé : 0 €.

## Lancer

```bash
cd backend
pip install -r requirements-dev.txt
cp .env.example .env            # puis renseigner FACTS_LLM_API_KEY
python -m pytest                # 353 tests, aucun appel réseau réel
uvicorn app.main:app --reload --ws-max-size 16384
```

`--ws-max-size` est important : le défaut d'uvicorn (16 Mo) laisse un client envoyer des trames énormes.
Documentation interactive : http://localhost:8000/docs (désactivée si `FACTS_ENV=prod`).

## Test en conditions réelles (avec tes vraies clés)

```bash
cd backend
cp .env.example .env        # renseigner FACTS_LLM_API_KEY et FACTS_TAVILY_API_KEY (.env est ignoré par git)
python scripts/smoke_live.py
```

Étapes : Tavily (1 crédit), Wikipédia, DuckDuckGo, LLM (appel minimal), puis une vérification complète
(jusqu'à 2 crédits Tavily). Options : `--skip-llm`, `--skip-pipeline`, `--assertion "..."`.
Aucune clé n'est affichée. Ce script n'est pas lancé par `pytest` ni par la CI.

Puis, pour tester l'API et les salons comme le fera le front :

```bash
uvicorn app.main:app --reload --ws-max-size 16384
curl -s localhost:8000/api/v1/check -H 'Content-Type: application/json' \
  -d '{"assertion": "Selon l\'INSEE, l\'inflation a dépassé 5 % en 2023."}'
```

## Architecture

```
app/
  core/       config, schémas Pydantic, sécurité, cache, scores de domaines   (aucune dépendance externe)
  adapters/   search.py (Tavily, Wikipédia, DuckDuckGo), search_chain.py (repli), llm.py   (le monde extérieur)
  services/   factcheck, retrieval, trust, rooms, message_checker, prompts    (la logique métier)
  api/        check.py (REST), rooms.py (REST + WebSocket), deps.py           (HTTP / WS)
  main.py     câblage (create_app)
```

Règle de dépendance : `api -> services -> adapters/core`. Recherche et LLM sont des **ports**
(`SearchProvider`, `LLMProvider`) : changer de fournisseur = écrire un adaptateur, rien d'autre ne bouge.

| Besoin futur | Où toucher |
|---|---|
| Autre moteur de recherche (Brave, Tavily, SearXNG) | nouvel adaptateur dans `adapters/search.py` |
| Autre LLM / SLM local (Ollama) | variables `FACTS_LLM_*`, aucun code |
| Plusieurs instances | `TTLCache`, `SlidingWindowRateLimiter` et `Room` -> Redis (même interfaces) |
| Persistance des débats | un dépôt (SQLite puis Postgres) injecté dans `Room` |

## Endpoints

- `POST /api/v1/check` : `{"assertion": "...", "institutional_filter": true}` -> verdict, confiance, deux perspectives, sources revalidées.
- `GET /api/v1/rooms?q=` : salons **publics** (salons par défaut d'abord, puis les plus actifs) ; `q` filtre par titre, catégorie ou ID, sans accents ni casse.
- `GET /api/v1/rooms/{id}` : recherche par ID. Un salon privé répond seulement `requires_code: true` (ni titre ni contenu).
- `POST /api/v1/rooms` : `{"title", "theme_category", "visibility": "public"|"private", "max_participants": 2-6, "spectators_allowed": bool, "participant_token"}` -> `{id, visibility, access_code}`. Le code (6 caractères) n'existe que pour un salon privé ; le propriétaire le retrouve dans le `snapshot` de son salon.
- `POST /api/v1/rooms/reformulate` : `{"title"}` -> `{title, theme_category}` : question neutre (≤ 120 caractères, jamais tronquée) et thème proposés par l'IA, **à accepter par l'utilisateur**. Refus en 422 avec une raison polie (sujet illégal, haineux, ciblant une personne, hors débat). **Le même contrôle s'applique à `POST /rooms`** (sinon il suffirait de ne pas cliquer) : un sujet refusé ne crée pas de salon et ne consomme pas le quota de création ; un titre déjà approuvé n'appelle pas l'IA une seconde fois ; si l'IA est en panne ou le quota de contrôles épuisé, la création reste possible. Un seul appel LLM, 10 par jour et par visiteur (`FACTS_DAILY_REFORMULATION_LIMIT`) ; une requête invalide ne consomme pas le quota. Sécurité : le sujet est une donnée (balises, nettoyage, détection d'injection) et la sortie du modèle est revalidée (thème en liste blanche, titre re-nettoyé, sans URL ni consigne).
- `GET /api/v1/rooms/status?ids=a,b` : parmi ces ID (historique du navigateur), lesquels existent encore -> `{existing: [...]}`. Ne révèle ni titre ni code.
- `POST /api/v1/rooms/{id}/delete` : `{participant_token}`. Réservé au créateur et seulement si le salon est vide (POST car CORS n'autorise que GET/POST).
- `WS /api/v1/rooms/{id}/ws` : salon en direct.
  - client -> serveur : **premier message obligatoire** `{"type": "hello", "token": "<jeton>", "code": "<code si privé>", "spectate": true|false}` (`spectate` : regarder sans prendre de siège, même s'il en reste ; refusé si le salon n'admet pas de spectateurs), puis `{"type": "message", "text": "..."}`.
  - serveur -> client : `snapshot` (rôle attribué + historique), `presence` (`{seats: ["A",…], max_participants, spectators}`), `message` (état `pending`), `check_result` (badge, sources, `trust_score`, `trust_delta`), `error` (`invalid_hello`, `invalid_code`, `too_many_attempts`, `session_replaced`, `spectators_not_allowed`, `room_full`, `room_deleted`, ...).

### Identité anonyme et salons créés par les utilisateurs

- Le navigateur génère un jeton aléatoire (22 à 64 caractères) et le garde en local ; le serveur n'en conserve que l'empreinte SHA-256 tronquée. Elle désigne le propriétaire d'un salon et garantit **un seul siège d'intervenant par personne** : une seconde connexion (autre onglet, reconnexion) remplace la première et hérite de son rôle.
- Places : 2 à 6 intervenants (sièges A à F, 2 par défaut) et jusqu'à 20 spectateurs, que le créateur peut interdire.
- Ce n'est pas un compte : vider le navigateur change d'identité. Des comptes pourront venir plus tard.
- Coût zéro, mémoire bornée : 50 salons maximum, 3 créations par jour et par visiteur, suppression d'un salon non permanent, vide et inactif depuis 30 minutes. Les 3 salons par défaut sont permanents.
- Salons privés : absents de la liste et de la recherche ; code comparé à temps constant ; 5 codes erronés par 10 minutes et par IP, puis plus aucun essai (même avec le bon code) jusqu'à la fin de la fenêtre.

## Pipeline du chatbot

1. SLM : 1-2 requêtes de recherche (repli sur l'assertion si le SLM échoue).
2. Code : recherche via la chaîne de repli (voir ci-dessous), dédoublonnage, classement par confiance du domaine.
3. SLM : analyse en JSON, puis **validation en code** (`finalize_analysis`) :
   URL absente de la recherche -> supprimée ; titre / domaine / score de confiance recalculés par le serveur ;
   aucune source valide -> « NON VÉRIFIABLE », points vidés, confiance plafonnée (30 sans source, 70 avec des sources faibles).

## Recherche web : chaîne de repli

Ordre par défaut (`FACTS_SEARCH_PROVIDERS=tavily,wikipedia,duckduckgo`) : le premier fournisseur disponible
qui trouve des résultats répond ; les suivants ne sont pas sollicités.

| Fournisseur | Coût | Protection |
|---|---|---|
| Tavily | 1 000 crédits/mois gratuits, 1 crédit par recherche « basic » | quota mensuel (`FACTS_TAVILY_MONTHLY_LIMIT`, 900 par défaut), ignoré sans `FACTS_TAVILY_API_KEY` |
| Wikipédia | gratuit, sans clé | contexte seulement : score de confiance 40, jamais devant une source institutionnelle |
| DuckDuckGo (`ddgs`) | gratuit, scraping non officiel | dernier recours, souvent bridé depuis un serveur cloud |

- **Disjoncteur** par fournisseur : après 3 échecs consécutifs, il est ignoré 120 s, puis un seul essai est autorisé.
- **Quota mensuel** : compté à la tentative (un appel échoué a pu coûter un crédit). Épuisé, on bascule sur le suivant sans appeler.
- **Cache 24 h** et **plafonds par visiteur** (30 vérifications/jour, 200 messages de salon/jour) pour ménager les crédits.
  Une vérification lance jusqu'à 2 recherches : avec 900 crédits, comptez 450 vérifications par mois au pire, davantage grâce au cache.
- Si aucun fournisseur ne peut répondre, l'API renvoie 502 : jamais de verdict sans sources.

## Trust meter

Le LLM classe chaque message (vérifié, à nuancer, non étayé, erroné) ; le score est une formule
déterministe lissée (`services/trust.py`), départ à 50. Il mesure la rigueur factuelle, jamais le camp :
participants anonymes, rôles A/B attribués par le serveur.

## Sécurité (tests dans `tests/test_security.py`, `test_api_*.py`, `test_factcheck_service.py`)

- Injection de prompt : nettoyage de l'entrée, délimiteurs, extraits web nettoyés aussi (injection indirecte), sortie validée par schéma, heuristique de détection.
- Anti-hallucination : sources revalidées, plafonds de confiance, pas d'appel LLM sans contexte de recherche.
- Abus : rate limiting par IP, taille de corps, taille de trame WS, quota de connexions par IP et par salon, plafond de vérifications simultanées (protège les quotas gratuits), déconnexion après erreurs répétées.
- WebSocket : contrôle de l'en-tête `Origin` (CORS ne protège pas les WS).
- Fuites : erreurs génériques côté client, aucun corps de réponse ni clé dans les messages d'erreur.
- Navigateur : CORS en liste blanche (jamais `*`), `nosniff`, `X-Frame-Options`, `no-store`, URL des sources limitées à http(s).

## Limites connues

- Adaptateurs Tavily et Wikipédia **non testés contre les vrais services** (réseau restreint pendant le développement) :
  les tests utilisent un transport factice. Points à valider avec une vraie clé : format d'authentification Tavily
  (la clé est envoyée en en-tête Bearer ET dans le corps, car la documentation consultée était ancienne),
  forme de la réponse Wikipédia, et limites de débit actuelles de chaque service.
- Recherche DuckDuckGo (`ddgs`) : scraping non officiel, peut être limité en débit, surtout depuis une IP de datacenter.
- Le plafond quotidien compte aussi les réponses servies par le cache (suivi par IP, en mémoire : repart à zéro au redémarrage).
- Quotas gratuits des fournisseurs LLM : à vérifier avant mise en ligne ; ils changent.
- État en mémoire : un redémarrage efface historique, cache et compteurs ; une seule instance.
- Heuristiques à ajuster avec de vrais usages : scores de domaines, poids du trust meter, filtre « message vérifiable » (présence d'un chiffre ou d'une source).
- Limite de corps basée sur `Content-Length` : ajouter aussi une limite côté hébergeur / reverse proxy.
- La détection d'injection par motifs se contourne ; les défenses structurelles (délimiteurs, validation de sortie) sont les vraies protections.

## Prochaines étapes

1. Brancher le front (`facts_app_preview.tsx`) sur ces endpoints à la place des données simulées.
2. Reformulation du thème par l'agent, modération (avertissements, exclusion), kick encadré par un score individuel.
3. Redis (offre gratuite) pour cache, rate limit et diffusion multi-instances.
4. CI GitHub Actions : `pytest` à chaque push.

## Modération (PR C)

Chaque message d'un salon passe, **avant publication**, par `app/services/moderation.py` :

1. **Filtre local gratuit** (texte normalisé : accents, leetspeak, lettres répétées) : insultes, menaces, racisme et haine évidents sont refusés sans appel LLM.
2. **Juge LLM** uniquement pour les messages *douteux* (mots ambigus) : un appel court, message enfermé dans `<MESSAGE>`, sortie limitée à `{illegal, category}`. Aucun texte libre du LLM n'est montré : le message d'avertissement vient d'une table fixe. Un message qui tente une injection n'est pas transmis au juge. Si le LLM est indisponible, un message douteux passe (le filtre local, lui, bloque toujours).
3. **Le débat reste libre** : critiquer idées, partis, responsables, même durement, est autorisé ; en cas de doute, on ne bloque pas.

Sanctions par identité (jeton), en mémoire, bornées : **1er message illégal = avertissement, 2e = dernier avertissement, 3e = exclusion de 1 h** (`FACTS_MODERATION_BAN_SECONDS`). Le message refusé n'est pas publié. Les avertissements s'oublient après 24 h sans récidive. L'exclusion vaut pour **tous les salons** : refus au `hello` (`error` code `banned` + `retry_after`) et refus de tout message.

**Signalement** : `{"type": "report", "message_id": N}` (entier strict). Un signalement ne sanctionne jamais directement : il déclenche un second avis (filtre + LLM). Si illégal, le message est remplacé par « [Message retiré par la modération] » (`message_removed`, score de confiance recalculé) et son auteur reçoit un avertissement. Garde-fous : pas d'auto-signalement, un signalement par personne et par message, un seul appel LLM par message quel que soit le nombre de signalements, 20 signalements jugés par jour et par identité, indisponibilité du juge = réessai possible, jamais de retrait.

Événements serveur ajoutés : `moderation` (`warning` | `final_warning` | `banned`), `message_removed`, `report_result` (`removed` | `kept` | `unavailable` | `duplicate` | `own` | `unknown`, envoyé au seul signaleur).

### Dictionnaire de modération (PR C2)

Les termes vivent dans `app/services/moderation_terms.py` (données, séparées de la logique) et sont testés par un **corpus de référence** (`tests/test_moderation_terms.py`) : phrases à refuser *et* phrases légitimes qui ne doivent jamais l'être.

| Niveau | Effet | Exemples |
|---|---|---|
| STRIKE | refusé **et compté** (avertissement → dernier avertissement → exclusion 1 h) | insultes directes, `vtf`, `ntm`, `fdp`, racisme, homophobie, menaces, `kys` |
| REPHRASE | refusé **sans avertissement compté** : « reformulez sans vulgarité » (`level: "rephrase"`) | « c'est de la merde », putain, bordel, bullshit |
| SUSPECT | tranché par le juge IA | « idiot », `tg`, « You're trash », NPC, mongol |

Texte normalisé avant comparaison : accents, leetspeak (`p3d@le`, seulement dans les mots mêlant lettres et chiffres, jamais « 2024 »), ponctuation (`f.d.p`), lettres espacées (`k y s`), répétitions (`connaaard`). Limites de mots partout : aucune recherche de sous-chaîne. **Volontairement absents** (sens légitime en débat) : SDF, PD, shit, ratio, gap, cancer, tard, retard, fac, Niger, argot de jeu vidéo. Mots à double sens : `FDP` (parti allemand/suisse → l'IA tranche), `pointeur` (laser, souris, badgeuse → autorisé ; sinon insulte).

Correctif du juge IA : la réponse était limitée à 60 jetons ; un modèle « raisonneur » (gpt-oss) les consommait en réflexion et la réponse sortait vide (« réponse invalide », donc « Signalement impossible »). Désormais 400 jetons, un nouvel essai, et la cause est journalisée.

### Numéros de participants stables (PR C3)

Les lettres A à F sont des **sièges** : elles se libèrent et se réattribuent quand quelqu'un part. Les messages ne s'y réfèrent plus. Chaque personne reçoit un **numéro stable par salon** (« Participant 1, 2, 3… », ordre d'arrivée, attribué à la première prise de siège) lié à son identité (jeton du navigateur, `sha256[:16]` côté serveur), pour toute la vie du salon :

- B part puis revient seul : il retrouve le siège A mais reste « Participant 2 » et ses anciens messages restent les siens ;
- C arrive sur l'ancien siège de B : il est « Participant 3 » et peut signaler les messages de B (l'auteur est retrouvé par identité, jamais par siège) ;
- supprimer un salon de « Mes salons » n'y change rien (ce n'est qu'un raccourci local) ;
- un spectateur n'a pas de numéro et n'en consomme pas ; plusieurs onglets d'une même personne partagent le même numéro ; mémoire bornée (500 identités par salon).

Protocole : `message.speaker` est un entier ; `snapshot.you` donne **mon** numéro (`null` pour un spectateur) ; `presence` devient `{present: [numéros connectés], max_participants, spectators}`. L'avenir « compte utilisateur » consistera à rattacher le jeton à un compte, sans toucher à ce mécanisme.

### Exclusion par score individuel (PR D)

Chaque message vérifié compte pour son auteur : le **score individuel** (même formule que le score du salon) n'existe qu'à partir de **3 messages vérifiés** ; un message retiré par la modération est décompté. Le créateur choisit le seuil à la création (`kick_threshold`, entier strict 20–40, défaut 30).

- `{"type":"kick","target":N}` : **créateur seulement**. Refusé si : cible absente, c'est le créateur lui-même, salon sans créateur (salons d'exemple), moins de 3 messages vérifiés, score au-dessus du seuil, vote déjà en cours, ou délai de grâce de 5 min après un vote perdu.
- **Sans spectateur** : le créateur décide seul (exclusion immédiate). **Avec spectateurs** : vote de 45 s ; le créateur compte pour un « pour » ; adopté si « pour » > « contre » (égalité = la personne reste) ; clôture anticipée quand tous ont voté ; annulé si la cible part ; le score est revérifié à la clôture.
- `{"type":"vote","approve":bool}` : **spectateurs seulement**, un vote par identité (les identités des votants ne sont jamais envoyées, seulement les totaux).
- Une personne exclue reçoit `error kicked`, la connexion est fermée (1008) et **elle ne peut plus rejoindre ce salon** (mémorisé par identité pour la durée de vie du salon). Son siège est libéré.
- `{"type":"take_seat"}` : un spectateur prend un siège libre (premier arrivé, premier servi, attribution atomique) ; il reçoit `{"type":"role","role","you"}` puis la présence est rediffusée.
- Événements : `kick_vote {target, score, threshold, yes, no, ends_in, voters}`, `kick_result {target, outcome: kicked|kept|cancelled}` ; `presence.scores` et `snapshot.kick_vote`.
- **Salons sans créateur** (salons d'exemple) : personne ne peut proposer ni voter, donc exclusion **automatique** sous 20 % (score individuel < 20, avec au moins 3 messages vérifiés), sans vote, avec la même interdiction de revenir. Le contrôle s'applique aussi à la reconnexion d'une personne qui était absente au moment du verdict. Attention : 3 messages « erronés » donnent exactement 20 % ; il en faut un 4e pour passer sous le seuil.

### Tri des affirmations (PR E)

La règle gratuite (`is_checkable` : chiffres, « selon », « étude »…) rate les faits sans chiffre (« Le gouvernement a supprimé l'ISF ») et déclenche à tort sur « Selon moi… » ou « Par rapport à… ». `claim_triage.py` ajoute un second avis du LLM, qui décide s'il y a une **affirmation vérifiable** et laquelle ; c'est cet extrait qu'on vérifie.

- Sont triés : tout message d'au moins 40 caractères et tout message que la règle retient, **sauf les questions** (règle seule, comme avant).
- **L'extrait doit être littéral** : une phrase reformulée ou inventée par le LLM est écartée (personne n'est noté sur ce qu'il n'a pas écrit). Un message qui ressemble à une injection n'est jamais envoyé au LLM.
- Panne, délai ou JSON invalide : la règle sert de filet (message retenu = vérifié en entier ; sinon « non évalué »), **jamais de pénalité sur une panne**.
- **Conditionnel chiffré** (« Cela pourrait entraîner une baisse de 50 % des recettes ») : c'est une estimation qu'on peut confronter à des études, donc vérifiable. Le prompt le dit (règle 8) et un filet déterministe ne laisse pas le tri écarter un message qui avance un chiffre, sauf formule d'opinion (« je trouve que… »). Une prédiction vague sans chiffre reste un argument.
- **Extrait recopié avec une variante typographique** (« 50 % » / « 50% », « État » / « Etat », apostrophe courbe, espace insécable) : accepté. Un extrait vraiment absent du message n'est plus classé « aucun fait » mais « non évalué » (repli sur la règle, jamais de pénalité).
- Coût : un appel LLM de plus par message concerné. `FACTS_CLAIM_TRIAGE=false` revient à la règle seule.
- Jeu annoté : `tests/data/claim_cases.py` (58 messages). Les tests valident le câblage avec un faux LLM « oracle » ; la qualité du vrai modèle se mesure avec `python -m scripts.eval_triage` (clé requise, ~58 requêtes).

### Répondre à un message (PR F)

`{"type":"message","text":"…","reply_to":<id>}` : `reply_to` est un entier strict (optionnel). Le serveur **vérifie** que le message existe dans l'historique du salon et n'a pas été retiré, puis reprend **lui-même** le numéro de l'auteur et un aperçu (120 caractères) : le client ne peut pas faire dire n'importe quoi à quelqu'un. Un identifiant inconnu ou un message retiré est refusé (`invalid_message`) et rien n'est publié.

- **Contexte de vérification** : le message cité (nettoyé, 300 caractères au plus, ignoré s'il ressemble à une injection) est transmis au tri et au vérificateur dans une balise `<CONTEXT>` / `<CONTEXT_MESSAGE>`. Il sert uniquement à comprendre « cela », « cette loi », « en 2017 » : il n'est ni vérifié, ni cité comme source, ni utilisé comme preuve, et le tri ne peut jamais en extraire un fragment (l'extrait doit venir du message). Le contexte fait partie de la clé de cache.
- **Réponses elliptiques** (« C'est faux. ») : pas de reformulation par le LLM. Sans fait énoncé par l'auteur, elles restent non vérifiables.
- Quand un message est retiré par la modération, l'aperçu des réponses existantes est remplacé par « [Message retiré par la modération] ».

### Saisie vocale (PR G)

`POST /api/v1/transcribe` : l'audio brut (≤ 30 s) est transcrit par Groq Whisper (`whisper-large-v3-turbo`, français) ; `GET /api/v1/features` indique au front si le micro doit être proposé. Le texte revient dans le champ de saisie pour **relecture** : il n'est jamais envoyé automatiquement. L'audio n'est ni écrit sur disque ni conservé.

- Corps = audio brut (pas de multipart), en-tête `X-Participant-Token` (identité). Le type annoncé ne prouve rien : le format est vérifié par ses **premiers octets** (webm, ogg, mp4, wav, mp3).
- Plafonds : 1 Mo par envoi (lu en flux, même sans `Content-Length`), 6 requêtes/min par IP, **20 messages vocaux par personne et par jour**, 60 par IP et par jour, et un **budget global de 20 000 s d'audio par jour** (Groq offre ~28 800 s) au-delà duquel la voix se ferme pour tous (503) sans bloquer le compte Groq. Chaque requête compte 10 s minimum, comme chez Groq.
- Durée réelle lue dans la réponse du fournisseur : > 33 s refusé. Segments de silence et phrases fantômes de Whisper (« Sous-titres réalisés par… ») écartés ; transcription nettoyée et plafonnée à 2 000 caractères.
- Réglages : `FACTS_STT_ENABLED`, `FACTS_STT_API_KEY` (vide = réutilise `FACTS_LLM_API_KEY`), `FACTS_STT_MODEL`, `FACTS_STT_DAILY_PER_PERSON`, `FACTS_STT_GLOBAL_DAILY_SECONDS`… Sans clé, la voix est simplement désactivée.
