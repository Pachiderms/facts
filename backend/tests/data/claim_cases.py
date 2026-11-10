"""Messages de débat annotés à la main : contiennent-ils une affirmation factuelle vérifiable ?

`claim=True`  : le message affirme un fait qu'on peut confronter à des sources (chiffré ou non).
`claim=False` : opinion, valeur, question, prédiction, attaque, procédure, définition conventionnelle…
`hard=True`   : cas piégeux (ambigu pour une règle simple comme pour un modèle).
Le champ `fact` donne, pour les affirmations, la phrase qu'on s'attend à voir extraite.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    text: str
    claim: bool
    kind: str
    fact: str = ""
    hard: bool = False


CASES: tuple[Case, ...] = (
    # ---- affirmations chiffrées ----
    Case("Le chômage est passé sous les 8 % en 2023.", True, "fait chiffré", "Le chômage est passé sous les 8 % en 2023."),
    Case("L'Espagne a augmenté son salaire minimum de 47% en 5 ans.", True, "fait chiffré", "L'Espagne a augmenté son salaire minimum de 47% en 5 ans."),
    Case("La dette publique dépasse 3 000 milliards d'euros.", True, "fait chiffré", "La dette publique dépasse 3 000 milliards d'euros."),
    Case("La moitié des Français vit avec moins de 2 000 euros par mois.", True, "fait chiffré", "La moitié des Français vit avec moins de 2 000 euros par mois."),
    Case("Les prix de l'énergie ont doublé en dix ans.", True, "fait chiffré", "Les prix de l'énergie ont doublé en dix ans."),
    Case("Cela rapporterait des centaines de millions d'euros chaque année.", True, "fait chiffré", hard=True, fact="Cela rapporterait des centaines de millions d'euros chaque année."),
    # ---- affirmations factuelles SANS chiffre (point faible de la règle) ----
    Case("Le gouvernement a supprimé l'ISF en 2017.", True, "fait sans chiffre", "Le gouvernement a supprimé l'ISF en 2017."),
    Case("Le gouvernement a supprimé l'impôt sur la fortune au début du quinquennat.", True, "fait sans chiffre", "Le gouvernement a supprimé l'impôt sur la fortune au début du quinquennat."),
    Case("La France est sortie du commandement intégré de l'OTAN sous de Gaulle.", True, "fait sans chiffre", "La France est sortie du commandement intégré de l'OTAN sous de Gaulle."),
    Case("L'Allemagne a fermé ses dernières centrales nucléaires.", True, "fait sans chiffre", "L'Allemagne a fermé ses dernières centrales nucléaires."),
    Case("La retraite à 60 ans a été instaurée par la gauche.", True, "fait sans chiffre", "La retraite à 60 ans a été instaurée par la gauche."),
    Case("Le Royaume-Uni a quitté l'Union européenne par référendum.", True, "fait sans chiffre", "Le Royaume-Uni a quitté l'Union européenne par référendum."),
    Case("Le Conseil constitutionnel a censuré cette disposition.", True, "fait sans chiffre", "Le Conseil constitutionnel a censuré cette disposition."),
    Case("Les socialistes ont voté contre cette loi à l'Assemblée.", True, "fait sans chiffre", "Les socialistes ont voté contre cette loi à l'Assemblée."),
    Case("La Suède n'a jamais confiné sa population pendant le Covid.", True, "fait sans chiffre", "La Suède n'a jamais confiné sa population pendant le Covid.", hard=True),
    Case("Le nucléaire est la première source d'électricité en France.", True, "fait sans chiffre", "Le nucléaire est la première source d'électricité en France."),
    Case("Aucun pays européen n'a de salaire minimum aussi élevé.", True, "fait sans chiffre", "Aucun pays européen n'a de salaire minimum aussi élevé.", hard=True),
    Case("Cette réforme a déjà été tentée en 1995 et abandonnée.", True, "fait chiffré", "Cette réforme a déjà été tentée en 1995 et abandonnée."),
    # ---- affirmations avec source citée ----
    Case("Selon l'INSEE, la pauvreté a augmenté l'an dernier.", True, "source citée", "Selon l'INSEE, la pauvreté a augmenté l'an dernier."),
    Case("Une étude de l'OFCE le démontre.", True, "source citée", "Une étude de l'OFCE le démontre.", hard=True),
    Case("Le rapport de la Cour des comptes est sans appel sur ce point.", True, "source citée", "Le rapport de la Cour des comptes est sans appel sur ce point.", hard=True),
    # ---- opinions et jugements de valeur ----
    Case("Je ne suis pas d'accord avec cette approche.", False, "opinion"),
    Case("C'est une mauvaise idée, point final.", False, "opinion"),
    Case("Baisser les impôts des classes moyennes serait plus égalitaire.", False, "opinion", hard=True),
    Case("Cette politique est injuste envers les travailleurs.", False, "opinion"),
    Case("Le modèle social français reste le meilleur du monde.", False, "opinion", hard=True),
    Case("L'immigration est une chance pour notre pays.", False, "opinion", hard=True),
    Case("La liberté individuelle devrait passer avant tout.", False, "valeur"),
    Case("Il faut absolument réformer l'école en profondeur.", False, "valeur"),
    # ---- opinions qui piègent la règle (mots déclencheurs sans fait) ----
    Case("Selon moi, c'est une erreur historique.", False, "piège règle", hard=True),
    Case("Par rapport à votre position, la mienne est plus raisonnable.", False, "piège règle"),
    Case("Je vous le dis, il y a mille raisons de s'inquiéter.", False, "piège règle", hard=True),
    Case("Ce taux de mensonge dans vos propos est délirant.", False, "piège règle"),
    Case("Un tiers de vos arguments sont de la pure rhétorique, à mon avis.", False, "piège règle", hard=True),
    Case("Il y a deux façons de voir les choses : la vôtre et la bonne.", False, "piège règle"),
    Case("Cent fois sur le métier remettez votre ouvrage, dit-on.", False, "piège règle"),
    Case("D'après moi, vous n'avez pas lu le texte.", False, "piège règle"),
    # ---- questions ----
    Case("Pouvez-vous citer votre source pour ce chiffre ?", False, "question"),
    Case("Pourquoi refusez-vous toute discussion sur le sujet ?", False, "question"),
    Case("Est-ce que vous seriez prêt à changer d'avis ?", False, "question"),
    Case("Qui paierait cette mesure à votre avis ?", False, "question"),
    # ---- attaques ad hominem / rhétorique (la modération s'en occupe) ----
    Case("Vous caricaturez ma position depuis le début.", False, "attaque"),
    Case("Vous ne répondez jamais aux questions qu'on vous pose.", False, "attaque", hard=True),
    Case("Encore un argument fumeux de votre part.", False, "attaque"),
    # ---- prédictions et hypothèses ----
    Case("Cette réforme va ruiner le pays dans les années à venir.", False, "prédiction", hard=True),
    Case("Si on baisse les impôts, la croissance repartira forcément.", False, "prédiction", hard=True),
    Case("Dans vingt ans, plus personne ne voudra de ce système.", False, "prédiction"),
    # ---- procédure, politesse, relances ----
    Case("Merci pour votre réponse, passons au point suivant.", False, "procédure"),
    Case("Pouvons-nous revenir au sujet de départ ?", False, "procédure"),
    Case("Je reformule : ma question portait sur l'efficacité, pas sur le coût.", False, "procédure"),
    Case("D'accord, je concède ce point.", False, "procédure"),
    Case("Bonjour à tous, ravi de débattre avec vous.", False, "procédure"),
    # ---- définitions et positions déclarées ----
    Case("Pour moi, être de gauche, c'est défendre les services publics.", False, "définition"),
    Case("Je suis favorable à la retraite par capitalisation.", False, "position", hard=True),
    Case("Mon parti défend depuis toujours cette idée.", False, "position", hard=True),
    # ---- mixtes : fait + opinion dans le même message ----
    Case("C'est scandaleux : le gouvernement a supprimé l'ISF en 2017 pour les plus riches.", True, "mixte", "le gouvernement a supprimé l'ISF en 2017 pour les plus riches", hard=True),
    Case("Évidemment que vous avez tort, la Suède n'a jamais confiné sa population.", True, "mixte", "la Suède n'a jamais confiné sa population", hard=True),
    Case("Je trouve que 35 heures, c'est trop peu, mais ce n'est que mon avis.", False, "mixte", hard=True),
)
