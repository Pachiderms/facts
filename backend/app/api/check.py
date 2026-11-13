"""Endpoint du mode chatbot : POST /api/v1/check."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.adapters.llm import LLMError, LLMRateLimitError
from app.adapters.search import SearchError
from app.api.deps import enforce_daily_check_limit, get_service, enforce_rate_limit
from app.core.schemas import CheckRequest, CheckResponse
from app.core.security import InvalidInputError
from app.services.factcheck import AnalysisError, FactCheckService, PromptInjectionError

logger = logging.getLogger("facts.api")
router = APIRouter(prefix="/api/v1", tags=["check"])


@router.post("/check", response_model=CheckResponse, dependencies=[Depends(enforce_rate_limit)])
async def check(
    request: Request, body: CheckRequest, service: FactCheckService = Depends(get_service)
) -> CheckResponse:
    # Plafond quotidien appliqué APRÈS validation du corps : une requête invalide (422) ne coûte
    # ni recherche ni appel LLM, elle ne doit donc pas consommer le crédit du visiteur.
    await enforce_daily_check_limit(request)
    # Les messages d'erreur sont volontairement génériques : aucun détail interne
    # (URL du fournisseur, clé, trace) ne doit fuiter vers le client.
    try:
        return await service.check(body.assertion, body.institutional_filter)
    except PromptInjectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except InvalidInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except LLMRateLimitError:
        raise HTTPException(status_code=503, detail="Service momentanément saturé, réessayez plus tard.", headers={"Retry-After": "30"}) from None
    except SearchError:
        logger.warning("recherche web indisponible")
        raise HTTPException(status_code=502, detail="La recherche web est momentanément indisponible.") from None
    except (LLMError, AnalysisError):
        logger.warning("analyse indisponible")
        raise HTTPException(status_code=502, detail="L'analyse est momentanément indisponible.") from None
