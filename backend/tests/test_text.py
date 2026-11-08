import pytest

from app.core.text import fit_sentences, is_complete

# Cas réel observé : la note était coupée net à 200 caractères (« ...l'augmentation du S »).
REAL = (
    "Le taux de pauvreté en France est de 15,4 % en 2024, mais il est stable depuis 2023 et n'a pas connu de hausse "
    "récente marquée. Aucun élément des sources ne permet de confirmer que l'augmentation du SMIC réduirait la pauvreté."
)


def test_regression_real_case_is_never_cut_mid_sentence():
    out = fit_sentences(REAL, 200)
    assert out == "Le taux de pauvreté en France est de 15,4 % en 2024, mais il est stable depuis 2023 et n'a pas connu de hausse récente marquée."
    assert is_complete(out) and len(out) <= 200


def test_short_complete_text_is_unchanged():
    assert fit_sentences("Phrase courte.", 200) == "Phrase courte."


def test_whitespace_is_normalised():
    assert fit_sentences("Une   phrase\n\ncoupée.", 100) == "Une phrase coupée."


def test_keeps_as_many_whole_sentences_as_fit():
    assert fit_sentences("Un. Deux. Trois.", 10) == "Un. Deux."


def test_decimal_numbers_do_not_split_sentences():
    assert fit_sentences("Le taux est de 15,4 % cette année. Autre phrase.", 40) == "Le taux est de 15,4 % cette année."


def test_single_overlong_sentence_is_cut_at_a_word_with_ellipsis():
    out = fit_sentences("mot " * 100 + "fin.", 50)
    assert out.endswith("…") and len(out) <= 50
    assert not out[:-1].endswith(" ") and out[:-1].endswith("mot")


def test_never_cuts_inside_a_word():
    text = "Extraordinairement long sans aucune ponctuation finale dans ce texte"
    out = fit_sentences(text, 30)
    assert out.endswith("…")
    assert set(out[:-1].split()) <= set(text.split())


def test_model_output_cut_mid_sentence_drops_the_dangling_fragment():
    assert fit_sentences("Première phrase complète. Seconde phrase coupée au milieu de l'augm", 500) == "Première phrase complète."


def test_unterminated_text_only_gets_an_ellipsis():
    out = fit_sentences("Texte sans point final", 500)
    assert out == "Texte sans point final…"


def test_empty_and_blank():
    assert fit_sentences("", 10) == ""
    assert fit_sentences("   \n ", 10) == ""


@pytest.mark.parametrize("limit", [1, 2, 5, 17, 80, 300])
def test_never_exceeds_limit_and_always_ends_cleanly(limit):
    for text in (REAL, "mot " * 200, "A. B. C. D. E. F.", "Sans ponctuation du tout"):
        out = fit_sentences(text, limit)
        assert len(out) <= limit or limit < 2
        assert out == "" or is_complete(out)


@pytest.mark.parametrize("ok", ["Fini.", "Vraiment ?", "Oui !", "Suite…", "« cité »"])
def test_is_complete_true(ok):
    assert is_complete(ok)


@pytest.mark.parametrize("ko", ["l'augmentation du S", "virgule,", "deux-points :"])
def test_is_complete_false(ko):
    assert not is_complete(ko)
