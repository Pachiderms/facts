import type { ReactNode } from 'react'
import { HOSTS, PUBLISHER } from '../lib/legal'
import { legalHref, PRICING_HREF, type LegalDoc } from '../lib/route'

/** Valeur à compléter : affichée en évidence tant qu'elle est vide (jamais une mention silencieusement absente). */
function Field({ value }: { value: string }) {
  return value.trim() ? (
    <span className="font-semibold text-neutral-900">{value}</span>
  ) : (
    <mark data-todo className="rounded bg-amber-100 px-1 font-semibold text-amber-900">
      À compléter
    </mark>
  )
}

const H2 = ({ children }: { children: ReactNode }) => <h2 className="mt-6 text-sm font-extrabold text-neutral-900">{children}</h2>
const P = ({ children }: { children: ReactNode }) => <p className="mt-2 text-xs leading-relaxed text-neutral-700">{children}</p>
const UL = ({ items }: { items: ReactNode[] }) => (
  <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-relaxed text-neutral-700">
    {items.map((item, i) => (
      <li key={i}>{item}</li>
    ))}
  </ul>
)

function Mentions() {
  return (
    <>
      <H2>Éditeur du site</H2>
      <P>
        CaFaitDebat. est édité par <Field value={PUBLISHER.name} />, entrepreneur individuel (micro-entreprise), SIRET <Field value={PUBLISHER.siret} />.
      </P>
      <P>
        Adresse : <Field value={PUBLISHER.address} />. Contact : <Field value={PUBLISHER.email} />.
      </P>
      <P>
        Directeur de la publication : <Field value={PUBLISHER.director} />.
      </P>
      <H2>Hébergement</H2>
      <UL items={HOSTS.map((h) => `${h.role} : ${h.name}, ${h.address}.`)} />
      <H2>Nature du service</H2>
      <P>
        CaFaitDebat. propose une vérification assistée par intelligence artificielle d’affirmations et des salons de débat. Les verdicts sont
        produits automatiquement à partir de sources publiques : ils peuvent comporter des erreurs et ne constituent ni un conseil juridique,
        ni une information officielle. Consultez toujours les sources citées.
      </P>
      <H2>Propriété intellectuelle et signalement</H2>
      <P>
        Le code et la charte du site sont la propriété de leur éditeur. Les messages publiés dans les salons restent la responsabilité de leurs
        auteurs. Pour signaler un contenu illicite, écrivez à <Field value={PUBLISHER.email} />.
      </P>
    </>
  )
}

function Confidentialite() {
  return (
    <>
      <P>
        Responsable du traitement : <Field value={PUBLISHER.name} /> (<Field value={PUBLISHER.email} />). Nous collectons le strict nécessaire
        et n’utilisons aucun traceur publicitaire ni outil d’analyse d’audience.
      </P>
      <H2>Données traitées</H2>
      <UL
        items={[
          <>
            <strong>Sans compte</strong> : un identifiant aléatoire stocké dans votre navigateur (pour votre place dans un salon) et une
            empreinte de votre adresse IP, salée et non réversible, servant uniquement aux plafonds quotidiens. Votre adresse IP n’est pas
            conservée en clair.
          </>,
          <>
            <strong>Avec un compte</strong> (connexion Google ou par e-mail) : votre adresse e-mail et, pour Google, l’identifiant Google
            associé (ni nom, ni photo), des sessions révocables et l’historique de vos salons (sans code d’accès).
          </>,
          <>
            <strong>Connexion par e-mail</strong> : l’adresse saisie sert à vous envoyer un code à usage unique. Seule une empreinte
            chiffrée de ce code est conservée, 10 minutes au plus, puis supprimée dès qu’il a servi.
          </>,
          <>
            <strong>Texte soumis</strong> : les affirmations à vérifier et les messages de débat sont envoyés à un service d’IA et à des moteurs
            de recherche pour produire le verdict. N’y saisissez pas de données sensibles ni de données concernant des tiers.
          </>,
          <>
            <strong>Voix</strong> : un enregistrement dicté est transcrit puis n’est pas conservé.
          </>,
          <>
            <strong>Abonnement Pro</strong> : le prestataire de paiement traite vos données bancaires ; nous ne les recevons jamais. Nous
            conservons seulement l’état de l’abonnement (statut, date de fin de période, identifiants chez le prestataire).
          </>,
        ]}
      />
      <H2>Finalités et bases légales</H2>
      <UL
        items={[
          'Fournir le service demandé (exécution du contrat ou mesures précontractuelles).',
          'Protéger le service et ses quotas contre les abus (intérêt légitime).',
          'Gérer l’abonnement et respecter nos obligations comptables et fiscales (contrat, obligation légale).',
        ]}
      />
      <H2>Sous-traitants</H2>
      <UL
        items={[
          'Hébergement : Cloudflare, Render, Neon (voir mentions légales).',
          'Connexion : Google (identification par jeton ; aucun cookie publicitaire de notre part) et Resend (envoi des e-mails contenant le code de connexion).',
          'Intelligence artificielle : Groq (traitement du texte à vérifier).',
          'Paiement et facturation : Lemon Squeezy, qui agit comme vendeur (marchand de référence) et gère la TVA.',
        ]}
      />
      <P>Certains de ces prestataires sont situés hors de l’Union européenne ; les transferts s’appuient sur leurs garanties contractuelles.</P>
      <H2>Durées de conservation</H2>
      <UL
        items={[
          'Compte et historique : jusqu’à la suppression du compte (immédiate, depuis le menu du compte).',
          'Sessions : 30 jours, révocables à tout moment.',
          'Code de connexion par e-mail : 10 minutes au plus, supprimé dès son utilisation.',
          'Compteurs de quotas : 2 jours.',
          'Données de facturation : durée légale de conservation des pièces comptables.',
        ]}
      />
      <H2>Vos droits</H2>
      <P>
        Vous pouvez accéder à vos données, les exporter et supprimer votre compte depuis le menu du compte. Pour tout autre droit
        (rectification, opposition, limitation), écrivez à <Field value={PUBLISHER.email} />. Vous pouvez aussi saisir la CNIL (cnil.fr).
      </P>
      <H2>Stockage dans votre navigateur</H2>
      <P>
        Le site utilise le stockage local de votre navigateur pour son fonctionnement (identifiant anonyme, session, historique, codes de salons
        privés), sans suivi publicitaire. Ces éléments sont indispensables au service.
      </P>
    </>
  )
}

function Cgu() {
  return (
    <>
      <H2>1. Objet</H2>
      <P>
        Les présentes conditions encadrent l’usage de CaFaitDebat., édité par <Field value={PUBLISHER.name} />. Utiliser le site vaut acceptation
        de ces conditions.
      </P>
      <H2>2. Service et limites</H2>
      <P>
        Le service fournit une vérification assistée par IA et des salons de débat. Les résultats sont donnés à titre informatif, sans garantie
        d’exactitude ni d’exhaustivité. Des plafonds quotidiens s’appliquent (visiteur, compte gratuit, abonné Pro) ; le service peut être
        interrompu ou ralenti, notamment en cas de forte sollicitation.
      </P>
      <H2>3. Règles d’usage</H2>
      <UL
        items={[
          'Pas de contenu illicite, haineux, diffamatoire, ni de harcèlement ou de divulgation de données personnelles de tiers.',
          'Pas d’usage automatisé abusif, de contournement des quotas ni de tentative d’atteinte à la sécurité du service.',
          'Les salons sont modérés (automatiquement et par leur créateur) : des messages peuvent être masqués et des participants exclus.',
        ]}
      />
      <H2>4. Compte</H2>
      <P>Le compte est facultatif et gratuit. Vous pouvez le supprimer à tout moment depuis son menu ; ses données sont alors effacées.</P>
      <H2>5. Abonnement Pro</H2>
      <UL
        items={[
          <>
            L’offre Pro (relèvement des plafonds quotidiens) est vendue par abonnement mensuel, tarif affiché sur la page{' '}
            <a className="font-bold underline" href={PRICING_HREF}>
              Tarifs
            </a>{' '}
            avant paiement.
          </>,
          'Le paiement est opéré par Lemon Squeezy, vendeur de l’abonnement (marchand de référence), qui émet la facture et gère la TVA.',
          'Le renouvellement est automatique ; la résiliation se fait à tout moment depuis le lien « Gérer mon abonnement » et prend effet à la fin de la période déjà payée.',
          'Droit de rétractation : pour un service numérique, le consommateur peut se rétracter sous 14 jours, sauf s’il a demandé l’exécution immédiate du service et renoncé à ce droit lors de la commande ; les conditions exactes sont précisées par le prestataire au moment du paiement.',
        ]}
      />
      <H2>6. Responsabilité</H2>
      <P>
        L’éditeur n’est pas responsable des décisions prises sur la base des verdicts ni des contenus publiés par les participants. Sa
        responsabilité est limitée dans la mesure permise par la loi ; les droits impératifs des consommateurs demeurent.
      </P>
      <H2>7. Modification et droit applicable</H2>
      <P>
        Ces conditions peuvent évoluer ; la version en vigueur est celle publiée sur cette page. Elles sont soumises au droit français. Pour toute
        réclamation : <Field value={PUBLISHER.email} />. Le consommateur peut recourir gratuitement à un médiateur de la consommation (coordonnées
        à compléter après désignation du médiateur).
      </P>
    </>
  )
}

const DOCS: Record<LegalDoc, { title: string; body: () => ReactNode }> = {
  mentions: { title: 'Mentions légales', body: Mentions },
  confidentialite: { title: 'Politique de confidentialité', body: Confidentialite },
  cgu: { title: 'Conditions générales d’utilisation', body: Cgu },
}

export function LegalPage({ doc }: { doc: LegalDoc }) {
  const { title, body: Body } = DOCS[doc]
  return (
    <article className="mx-auto max-w-3xl rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm sm:p-8">
      <h1 className="text-xl font-extrabold text-neutral-900">{title}</h1>
      <p className="mt-1 text-[11px] text-neutral-500">Dernière mise à jour : {PUBLISHER.updated}</p>
      <Body />
      <nav aria-label="Autres documents" className="mt-8 flex flex-wrap gap-x-4 gap-y-1 border-t border-neutral-200 pt-4 text-xs">
        {(Object.keys(DOCS) as LegalDoc[])
          .filter((d) => d !== doc)
          .map((d) => (
            <a key={d} href={legalHref(d)} className="font-bold text-neutral-700 underline hover:text-neutral-900">
              {DOCS[d].title}
            </a>
          ))}
      </nav>
    </article>
  )
}
