"""Mesure le tri des affirmations sur le VRAI modèle, avec le jeu annoté de tests/data/claim_cases.py.

    FACTS_LLM_API_KEY=... python -m scripts.eval_triage          (depuis backend/)

Consomme ~61 requêtes LLM (quota gratuit) : compter environ 7 minutes (pause de 7 s entre deux requêtes). Affiche rappel / précision de la règle seule et du tri, et les messages ratés.
"""

import asyncio

from app.adapters.llm import OpenAICompatibleLLM
from app.core.config import get_settings
from app.services.claim_triage import ClaimExtractor
from app.services.message_checker import is_checkable
from tests.data.claim_cases import CASES


def report(name: str, predictions: dict[str, bool]) -> None:
    tp = sum(1 for c in CASES if c.claim and predictions[c.text])
    fn = [c for c in CASES if c.claim and not predictions[c.text]]
    fp = [c for c in CASES if not c.claim and predictions[c.text]]
    print(f"\n== {name} : rappel {tp}/{tp + len(fn)} · précision {tp}/{tp + len(fp)}")
    for c in fn:
        print("  raté      :", c.text)
    for c in fp:
        print("  à tort    :", c.text)


async def main() -> None:
    s = get_settings()
    llm = OpenAICompatibleLLM(
        base_url=s.llm_base_url,
        model=s.llm_model,
        api_key=s.llm_api_key,
        timeout_seconds=s.llm_timeout_seconds,
        reasoning_effort=s.llm_reasoning_effort,
    )
    extractor, triaged, unavailable = ClaimExtractor(llm), {}, 0
    try:
        for c in CASES:
            r = await extractor.triage(c.text)
            unavailable += r.outcome == "unavailable"
            triaged[c.text] = r.outcome == "claim"
            await asyncio.sleep(7)  # le plafond Groq en jetons (~8 000/min) est atteint avant celui des requêtes (30/min)
    finally:
        await llm.aclose()
    report("règle seule", {c.text: is_checkable(c.text) for c in CASES})
    report("tri par le LLM", triaged)
    print(f"\nindisponibles : {unavailable}/{len(CASES)}")


if __name__ == "__main__":
    asyncio.run(main())
