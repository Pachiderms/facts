"""Test en conditions réelles : à lancer sur TA machine avec tes vraies clés (jamais en CI).

    cd backend
    cp .env.example .env     # puis renseigner FACTS_LLM_API_KEY et FACTS_TAVILY_API_KEY
    python scripts/smoke_live.py

Ce que fait le script, dans l'ordre (chaque étape est indépendante et affiche OK ou ECHEC) :
  1. Tavily      : 1 recherche                      -> consomme 1 crédit Tavily
  2. Wikipédia   : 1 recherche                      -> gratuit
  3. DuckDuckGo  : 1 recherche                      -> gratuit (peut être bridé)
  4. LLM         : 1 appel JSON minimal             -> consomme un peu de quota Groq
  5. Pipeline    : 1 vérification complète          -> jusqu'à 2 crédits Tavily + 2 appels LLM

Options : --skip-llm (étapes 4 et 5 ignorées), --skip-pipeline, --assertion "..."
Aucune clé n'est jamais affichée : seuls le nom du type d'erreur et un message générique le sont.
Code de sortie : 0 si tout passe, 1 sinon.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.llm import OpenAICompatibleLLM  # noqa: E402
from app.adapters.search import DuckDuckGoSearch, TavilySearch, WikipediaSearch  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import build_service  # noqa: E402

DEFAULT_ASSERTION = "Selon l'INSEE, l'inflation en France a dépassé 5 % en moyenne annuelle en 2023."
QUERY = "inflation France INSEE 2023"

results: list[tuple[str, bool]] = []


def report(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok))
    print(f"[{'OK    ' if ok else 'ECHEC '}] {name}: {detail}")


async def check_search(name: str, provider) -> None:
    t0 = time.monotonic()
    try:
        found = await provider.search(QUERY, 5)
    except Exception as exc:  # on n'affiche que le type : un message pourrait contenir du contenu distant
        report(name, False, f"{type(exc).__name__}: {exc}")
        return
    finally:
        closer = getattr(provider, "aclose", None)
        if closer:
            await closer()
    dt = time.monotonic() - t0
    if not found:
        report(name, False, f"réponse reçue mais 0 résultat ({dt:.1f}s) : format de réponse à vérifier")
        return
    domains = ", ".join(r.domain for r in found[:3])
    report(name, True, f"{len(found)} résultats en {dt:.1f}s (ex. {domains})")


async def check_llm(settings) -> bool:
    llm = OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    try:
        out = await llm.complete("Réponds uniquement par un objet JSON.", 'Renvoie {"ok": true}.', json_mode=True, max_tokens=30)
        report("LLM", True, f"réponse reçue ({len(out)} caractères)")
        return True
    except Exception as exc:
        report("LLM", False, f"{type(exc).__name__}: {exc}")
        return False
    finally:
        await llm.aclose()


async def check_pipeline(settings, assertion: str) -> None:
    service = llm = search = None
    try:
        service, llm, search = build_service(settings)
        t0 = time.monotonic()
        response = await service.check(assertion, True)
        dt = time.monotonic() - t0
        domains = ", ".join(s.domain for s in response.verified_sources) or "aucune"
        report("Pipeline", True, f"verdict « {response.verdict} », confiance {response.confidence_score}, "
                                 f"{len(response.verified_sources)} source(s) [{domains}] en {dt:.1f}s")
        print(f"          résumé : {response.summary[:200]}")
        if not response.verified_sources:
            print("          ATTENTION : aucune source validée (recherche vide ou URLs rejetées par la validation).")
    except Exception as exc:
        report("Pipeline", False, f"{type(exc).__name__}: {exc}")
    finally:
        if llm is not None:
            await llm.aclose()
        if search is not None:
            await search.aclose()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--skip-pipeline", action="store_true")
    parser.add_argument("--assertion", default=DEFAULT_ASSERTION)
    args = parser.parse_args()

    settings = get_settings()
    print(f"Configuration : fournisseurs={settings.search_providers!r}, modèle LLM={settings.llm_model!r}")
    print(f"                clé Tavily {'présente' if settings.tavily_api_key else 'ABSENTE'}, "
          f"clé LLM {'présente' if settings.llm_api_key else 'ABSENTE'}\n")

    if settings.tavily_api_key:
        await check_search("Tavily", TavilySearch(settings.tavily_api_key, settings.search_timeout_seconds))
    else:
        print("[IGNORE] Tavily: FACTS_TAVILY_API_KEY absente")
    await check_search("Wikipédia", WikipediaSearch(settings.wikipedia_lang, settings.search_timeout_seconds))
    await check_search("DuckDuckGo", DuckDuckGoSearch(timeout_seconds=settings.search_timeout_seconds))

    if not args.skip_llm:
        llm_ok = await check_llm(settings) if settings.llm_api_key else False
        if not settings.llm_api_key:
            report("LLM", False, "FACTS_LLM_API_KEY absente")
        if not args.skip_pipeline and llm_ok:
            await check_pipeline(settings, args.assertion)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} étapes réussies" + (f" ; échecs : {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
