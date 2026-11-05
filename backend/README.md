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
- `GET /api/v1/rooms` : liste des salons avec score de fiabilité.
- `WS /api/v1/rooms/{id}/ws` : salon en direct.
  - client -> serveur : `{"type": "message", "text": "..."}`
  - serveur -> client : `snapshot` (rôle attribué + historique), `presence`, `message` (état `pending`), `check_result` (badge, sources, `trust_score`, `trust_delta`), `error`.

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
2. Création de salons par les utilisateurs (avec authentification légère et quotas).
3. Redis (offre gratuite) pour cache, rate limit et diffusion multi-instances.
4. CI GitHub Actions : `pytest` à chaque push.
