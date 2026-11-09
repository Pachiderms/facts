"""Corpus de référence du dictionnaire : ce qui DOIT être refusé et ce qui ne doit JAMAIS l'être.

Ajouter un terme au dictionnaire = ajouter ici une phrase refusée ET (si le mot a un sens légitime)
une phrase autorisée : c'est ce qui empêche les faux positifs de type « Scunthorpe ».
"""

import pytest

from app.services.moderation import local_filter, normalize

STRIKE = [
    # abréviations
    ("vtf", "insulte"), ("Vtff", "insulte"), ("FTG", "insulte"), ("ntm", "insulte"), ("N.T.M", "insulte"),
    ("t'es qu'un fdp", "insulte"), ("f.d.p", "insulte"), ("f d p", "insulte"), ("stfu", "insulte"), ("Slp", "insulte"),
    # insultes françaises
    ("connard", "insulte"), ("Connasse", "insulte"), ("sal0pe", "insulte"), ("enculé", "insulte"), ("nkul", "insulte"),
    ("sale pute", "insulte"), ("fils de pute", "insulte"), ("trou du cul", "insulte"), ("espèce de merde", "insulte"),
    ("tu dis de la merde", "insulte"), ("vous racontez de la merde", "insulte"), ("ta gueule", "insulte"),
    ("nique ta mère", "insulte"), ("va te faire foutre", "insulte"), ("branleur", "insulte"), ("pétasse", "insulte"),
    # anglais
    ("fuck you", "insulte"), ("bitch", "insulte"), ("b!tch", "insulte"), ("asshole", "insulte"), ("you're a piece of shit", "insulte"),
    # racisme / haine
    ("sales arabes", "racisme"), ("sale race", "racisme"), ("bougnoule", "racisme"), ("youpin", "racisme"),
    ("nigger", "racisme"), ("N1gg@", "racisme"), ("kike", "racisme"), ("retourne dans ton pays", "racisme"),
    ("pédé", "haine"), ("gouine", "haine"), ("faggot", "haine"), ("retarded", "haine"), ("gogol", "haine"),
    ("ces migrants sont des parasites", "haine"),
    # menaces, incitation au suicide
    ("kys", "menace"), ("k.y.s", "menace"), ("k y s", "menace"), ("kill yourself", "menace"), ("va te suicider", "menace"),
    ("suicide-toi", "menace"), ("tu devrais te pendre", "menace"), ("je vais te tuer", "menace"), ("mort aux juifs", "menace"),
    ("va crever", "menace"),
]

REPHRASE = [
    "c'est de la merde", "Putain c'est n'importe quoi", "ce projet de loi est merdique", "bullshit", "ça me fait chier",
    "quel bordel", "fuck ce budget", "ptn",
]

# Mots du dictionnaire (ou proches) qui ont un sens légitime en débat : JAMAIS refusés d'office.
NEVER_BLOCKED = [
    "La FDP allemande refuse le budget", "Le FDP suisse a voté contre", "Le Niger a connu un coup d'État", "Le Nigeria et le Niger",
    "Les SDF sont de plus en plus nombreux", "Le PD italien soutient la loi", "Il faut le faire plus tard", "retard de paiement",
    "Le retard de la France en matière d'éducation", "légaliser le shit", "le ratio dette/PIB", "le gap salarial", "un écart de 12 %",
    "la fac de droit", "pointeur laser", "le pointeur de la souris", "cancer du pancréas", "Je finirai tard", "Un homme de 40 ans",
    "La consommation baisse", "Il a conclu l'accord", "la constitution", "un assassin présumé", "les Mongols ont conquis la Chine",
    "Budget 2024 : 1984 milliards", "Mont Saint-Michel", "d'après l'Insee, 12 %", "Le Conseil constitutionnel a statué",
    "uninstall", "touch grass", "skill issue", "noob", "ratio", "gap", "diff", "hardstuck", "cancer", "tard", "retard", "SDF", "PD",
    "Riton", "cdr", "blc", "rab", "cmb", "scs", "ffs", "idgaf", "milf",  # argot sans rapport avec un débat : pas filtré
    "Les prix de l'énergie ont augmenté de 20 %.", "Je ne suis pas d'accord avec ce ministre, sa politique est un échec.",
    "Ce projet de loi est une catastrophe économique.", "Les gens crèvent de faim dans cette région.",
    "Il y a eu un mort aux urgences cette nuit.",
]


@pytest.mark.parametrize("text,category", STRIKE)
def test_strike_terms_are_blocked(text, category):
    result = local_filter(text)
    assert (result.verdict, result.category) == ("block", category), text


@pytest.mark.parametrize("text", REPHRASE)
def test_vulgarity_without_target_asks_to_rephrase(text):
    assert local_filter(text).verdict == "rephrase", text


@pytest.mark.parametrize("text", NEVER_BLOCKED)
def test_legitimate_words_are_never_blocked_or_rephrased(text):
    assert local_filter(text).verdict in ("ok", "suspect"), text


@pytest.mark.parametrize("text", ["La FDP allemande refuse le budget", "les Mongols ont conquis la Chine"])
def test_ambiguous_with_legitimate_context_goes_to_the_judge_not_to_a_block(text):
    assert local_filter(text).verdict == "suspect"


def test_fdp_as_an_insult_is_still_blocked_without_political_context():
    assert local_filter("t'es qu'un fdp").verdict == "block"
    assert local_filter("Ferme ta gueule, FDP").verdict == "block"


def test_pointeur_as_a_slur_is_blocked_but_not_the_laser_or_the_mouse():
    assert local_filter("sale pointeur").verdict == "block"
    assert local_filter("pointeur laser").verdict == "ok"
    assert local_filter("le pointeur de la souris").verdict == "ok"


@pytest.mark.parametrize("text", ["You're trash", "you are garbage", "t'es un noob et un boloss"])
def test_insults_that_depend_on_context_are_left_to_the_judge(text):
    assert local_filter(text).verdict == "suspect", text


def test_tg_alone_is_not_blocked_the_judge_decides():
    assert local_filter("tg").verdict == "suspect"


def test_spaced_letters_are_glued_only_for_three_or_more_single_letters():
    assert normalize("k y s") == "kys"
    assert normalize("f.d.p") == "fdp"
    assert normalize("a b") == "a b"  # deux lettres : des mots, pas un contournement


def test_numbers_are_never_turned_into_letters():
    assert normalize("2024") == ""
    assert normalize("p3d@le") == "pedale"
    assert normalize("idiot !") == "idiot"
