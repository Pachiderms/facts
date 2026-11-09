"""Dictionnaire de modération passive : DONNÉES, séparées de la logique (`moderation.py`).

Les mots sont écrits sur la forme normalisée (minuscules, sans accents). Le texte est normalisé avant
comparaison : accents, leetspeak (`p3d@le`), ponctuation (`f.d.p`), lettres espacées (`k y s`).
`loose()` tolère les lettres répétées (`connaaard`) ; une limite de mot (`\\b`) évite les faux positifs
« Scunthorpe » (aucune recherche de sous-chaîne).

Niveaux :
  * STRIKE   : refusé ET compté (avertissement -> dernier avertissement -> exclusion 1 h) ;
  * REPHRASE : vulgarité sans cible, refusé SANS avertissement compté (« reformulez ») ;
  * SUSPECT  : ambigu, tranché par le juge IA (jamais bloqué d'office).

Ce qui est volontairement ABSENT (débat politique légitime, voir tests/test_moderation_terms.py) :
« SDF », « PD » (parti italien), « shit » (légalisation), « ratio », « gap », « cancer », « tard »,
« retard », « fac », « Niger » (pays), prénoms et argot de jeu vidéo.
"""

import re


def loose(phrase: str, plural: bool = True) -> str:
    """Motif d'un mot (ou d'une expression) qui tolère les lettres répétées et les pluriels."""
    words = [r"".join(re.escape(c) + "+" for c in w) for w in phrase.split()]
    return r"\b" + r"\s+".join(words) + (r"s?" if plural else "") + r"\b"


def any_of(*phrases: str, plural: bool = True) -> str:
    return "(?:" + "|".join(loose(p, plural) for p in phrases) + ")"


GROUPS = r"(?:arabes?|noirs?|juifs?|blancs?|negres?|roms?|musulmans?|chinois|asiatiques?|gays?|homos?|trans|migrants?|immigres?|etrangers?)"

# ---------------------------------------------------------------- STRIKE : (catégorie, motifs)
STRIKE: dict[str, tuple[str, ...]] = {
    "menace": (
        r"\bje (vais|vas|va) (te|vous|le|la|les) (tuer|buter|crever|masacrer|egorger|fumer|violer)\b",
        r"\bon va (te|vous|le|la|les) (tuer|buter|crever|masacrer|egorger|violer)\b",
        r"\b(il faut|faut) (tous )?(les |le |la )?(tuer|exterminer|gazer|egorger|pendre)\b",
        r"\bmort aux? (arabes|noirs|juifs|musulmans|roms|migrants|immigres|etrangers|gays|homos|blancs|flics|journalistes|politiques|riches|pauvres)\b",
        r"\b(va|vas|allez|allez vous) (creve|crever)\b",
        # incitation au suicide
        r"\bk+\s*y+\s*s+\b",
        r"\bkill\s+(your|ur|you)\s*self\b",
        r"\b(suicide|suicidez|suicides)\s+(toi|vous)\b",
        r"\b(va|vas|allez)\s+te\s+suicider\b",
        r"\b(tu|vous)\s+(devrais|devriez|ferais|feriez)\s+(mieux\s+)?(de\s+)?(te|vous)\s+(suicider|pendre|tuer)\b",
    ),
    "racisme": (
        rf"\bsales? {GROUPS}\b",
        r"\b(bougnoule|youpin|chinetoque|bamboula|sale race)s?\b",
        r"\bretourne[zs]? (dans ton|dans votre|chez toi|chez vous)\b",
        r"\bnigg+(er|a|ah|uh|az|as)s?\b",  # « nigg » : jamais « Niger » (le pays)
        r"\b(spic|spics|chink|chinks|wetback|wetbacks|kike|kikes)\b",
    ),
    "haine": (
        r"\b(pede|gouine|tafiole|tarlouze|triso|gogol|mongolien|mongoliens)s?\b",
        r"\bfa+g+o+t+s?\b|\bpha+g+o+t+s?\b",
        r"\bretarded\b",
        rf"\b(ces|les|tous les) {GROUPS} (sont des?|doivent|meritent)\b.{{0,40}}\b(animaux|vermines?|parasites?|rats?|mourir|crever|disparaitre|degager|deporter)\b",
    ),
    "insulte": (
        r"\b" + any_of("connard", "conard", "connasse", "conasse", "salope", "salop", "salopard", "slp", "pute", "encule", "enculee",
                       "enculer", "nkul", "nkule", "pouffiasse", "poufiasse", "petasse", "branleur", "branleuse",
                       "succeur", "suceuse", "crevard", plural=True) + r"\b",
        loose("fils de pute", False),
        loose("fille de pute", False),
        loose("trou du cul") + "|" + loose("trouduc") + "|" + loose("sous merde") + "|" + loose("sac a merde"),
        r"\b(ntmm?|ntm|vtff?|ftg|stfu|gtfo)\b",
        r"\b(ta|ferme ta|ferme la) gueule\b",
        r"\bva te faire (foutre|enculer)\b",
        r"\bnique[zr]? (ta|vos|ta putain de) (mere|race|gueule)\b",
        r"\bnique tes (morts|grands morts)\b",
        # insulte dirigée contre la personne ou ses propos (« tu dis de la merde », « t'es une merde »)
        r"\b(tu|vous|t) (es|etes|dis|dites|racontes|racontez|parles|parlez|ecris|ecrivez)\b.{0,25}\bme+rde?s?\b",
        r"\bespece de (merde|con|conne|connard|salope|abruti|abrutie|pute)\b",
        # anglais
        r"\b" + any_of("asshole", "ashole", "bitch", "biatch", "bytch", "cunt", "dickhead", "motherfucker", "muthafucka",
                       "shithead", "wanker", "twat", "slut", "whore", "skank") + r"\b",
        r"\bfuck (you|off|u)\b",
        r"\b(you|u|ur|youre) (are |re )?(a |an )?(piece of shit|dumb ?fuck|stupid ?bitch)\b",
    ),
}

# ---------------------------------------------------------------- REPHRASE : vulgarité sans cible
REPHRASE: tuple[str, ...] = (
    r"\b" + any_of("merde", "merdique", "putain", "ptn", "bordel", "foutre", "fuck", "fucking", "fk", "bullshit") + r"\b",
    r"\bchier\b|\bfait chier\b",
)

# ---------------------------------------------------------------- SUSPECT : tranché par le juge IA
SUSPECT: tuple[str, ...] = (
    r"\b" + any_of("con", "conne", "idiot", "idiote", "debile", "imbecile", "abruti", "abrutie", "stupide", "ordure", "degage",
                   "degagez", "vermine", "parasite", "racaille", "tare", "minable", "cretin", "cretine", "batard", "batarde",
                   "merdeux", "merdeuse", "negre", "negresse", "raton", "tapette", "pedale", "tocard", "tocarde", "bouffon",
                   "bouffonne", "boloss", "pouffe", "casos", "mongol", "mongole", "npc", "tdc", "tg", "bastard", "fag", "trash",
                   "garbage", "dogshit", "brainlet", "noob") + r"\b",
    r"\b(you|u|ur|youre) (are |re )?(a |an )?(trash|garbage|dogshit|worthless|idiot|moron|loser)\b",
    r"\b(race|races|inferieure?s?|sous hommes?|grand remplacement)\b",
    rf"\b(ces|les|tous les) {GROUPS} (sont|ne|doivent|veulent)\b",
    r"\b(je te|je vous|on va te|on va vous) (retrouve|retrouverai|retrouvera|trouve|trouverai|detruire|detruirai|casser|casserai)\b",
    r"\b(tu|vous) (merites?|meritez) (de )?(mourir|crever|souffrir)\b",
)

# Mots à double sens : (motif, contexte légitime, catégorie sans contexte, verdict avec contexte).
#  * « FDP » : insulte… ou parti libéral allemand/suisse -> avec contexte politique, le juge IA tranche ;
#  * « pointeur » : insulte grave (argot) mais aussi laser/souris/badgeuse -> avec ce contexte, autorisé.
AMBIGUOUS: tuple[tuple[str, str, str, str], ...] = (
    (
        r"\bf+d+u*p+s?\b",
        r"\b(allemand|allemande|allemagne|suisse|liberal|liberaux|coalition|bundestag|parti|lindner|ampel|scholz|(la|du|de la|les|des) fdp)\b",
        "insulte",
        "suspect",
    ),
    (
        r"\bpointeurs?\b",
        r"\b(laser|souris|curseur|ecran|badge|badgeuse|horloge|pointage|memoire|langage|variable|objet|poste|travail|salarie|employe|stylo|presentation)\b",
        "insulte",
        "ok",
    ),
)
