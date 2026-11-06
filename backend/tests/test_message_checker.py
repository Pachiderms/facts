import pytest

from app.core.schemas import CheckResponse, Source, View
from app.core.security import InvalidInputError
from app.services.factcheck import PromptInjectionError
from app.services.message_checker import FactCheckMessageChecker, MessageCheck, is_checkable


@pytest.mark.parametrize(
    "text",
    [
        "Le SMIC augmenterait de 15 % le coût du travail.",
        "Selon l'INSEE, l'inflation est contenue.",
        "D'après le Trésor, la mesure coûterait cher.",
        "Une étude de l'OFCE le démontre.",
        "Le rapport de la Cour des comptes est clair.",
        "L'Espagne a augmenté son salaire minimum de 47% en 5 ans.",
    ],
)
def test_checkable(text):
    assert is_checkable(text)


@pytest.mark.parametrize(
    "text",
    ["Je ne suis pas d'accord avec cette approche.", "C'est une mauvaise idée, point final.", "Vous caricaturez ma position."],
)
def test_pure_opinions_are_not_sent_to_the_llm(text):
    assert not is_checkable(text)


def response(verdict):
    return CheckResponse(
        verdict=verdict,
        confidence_score=80,
        summary="Synthèse " + "x" * 400,
        liberal_institutional_view=View(title="L", points=[]),
        heterodox_social_view=View(title="H", points=[]),
        verified_sources=[Source(title=f"T{i}", url=f"https://insee.fr/{i}", domain="insee.fr", trust_score=95) for i in range(5)],
    )


class FakeService:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    async def check(self, text, institutional_filter=True):
        if self.error:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    "verdict,status,badge",
    [("VRAI", "verified", "green"), ("À NUANCER", "nuanced", "amber"), ("FAUX", "false", "red"), ("NON VÉRIFIABLE", "unsourced", "amber")],
)
async def test_verdict_mapping(verdict, status, badge):
    check = await FactCheckMessageChecker(FakeService(response(verdict))).check("Le chiffre est 12")
    assert (check.status, check.badge_type) == (status, badge)


async def test_note_and_sources_are_bounded():
    check = await FactCheckMessageChecker(FakeService(response("VRAI"))).check("12")
    assert len(check.note) <= 300 and len(check.sources) == 3
    assert set(check.sources[0]) == {"title", "url", "domain"}


@pytest.mark.parametrize("error", [InvalidInputError("x"), PromptInjectionError("y")])
async def test_invalid_or_injection_message_is_left_unevaluated(error):
    check = await FactCheckMessageChecker(FakeService(error=error)).check("Ignore tout 12")
    assert check.status == "unchecked" and check.badge_type == "gray"


def test_factories():
    assert MessageCheck.pending().status == "pending"
    assert MessageCheck.no_claim().status == "no_claim"
    assert MessageCheck.unchecked("X").badge_text == "X"


async def test_note_is_never_cut_mid_sentence():
    """Régression : la note était coupée net à 200 caractères (« ...l'augmentation du S »)."""
    r = response("À NUANCER")
    r.summary = (
        "Le taux de pauvreté en France est de 15,4 % en 2024, mais il est stable depuis 2023 et n'a pas connu de hausse "
        "récente marquée. Aucun élément des sources ne permet de confirmer que l'augmentation du SMIC réduirait la pauvreté. "
        "Une troisième phrase qui dépasse largement la limite de trois cents caractères autorisée pour la note affichée sous le message."
    )
    check = await FactCheckMessageChecker(FakeService(r)).check("15,4 %")
    assert check.note.endswith(".") and len(check.note) <= 300
    assert "l'augmentation du SMIC réduirait la pauvreté." in check.note
    assert "troisième" not in check.note
