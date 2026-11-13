/**
 * Informations légales de l'éditeur : à COMPLÉTER ICI, une seule fois, avant d'ouvrir le paiement.
 * Les pages Mentions légales / Confidentialité / CGU les reprennent. Tant qu'une valeur vaut `TODO`, la page
 * l'affiche en évidence (« À compléter ») pour qu'aucune mention ne soit oubliée.
 */
export const TODO = '' // valeur vide = à compléter

export const PUBLISHER = {
  /** Nom et prénom de l'entrepreneur individuel (micro-entreprise : le nom de l'entrepreneur est le nom de l'éditeur). */
  name: TODO,
  /** Adresse postale (ou adresse de domiciliation de l'entreprise). */
  address: TODO,
  /** Adresse e-mail de contact (affichée publiquement). */
  email: TODO,
  /** Numéro SIRET délivré à la création de la micro-entreprise. */
  siret: TODO,
  /** Directeur de la publication (en micro-entreprise : l'entrepreneur). */
  director: TODO,
  /** Date de dernière mise à jour des documents. */
  updated: '13 novembre 2026',
} as const

export const HOSTS = [
  { role: 'Site web (fichiers statiques)', name: 'Cloudflare, Inc.', address: '101 Townsend St, San Francisco, CA 94107, États-Unis' },
  { role: 'Serveur applicatif (API)', name: 'Render Services, Inc.', address: '525 Brannan Street, Suite 300, San Francisco, CA 94107, États-Unis (région Francfort, UE)' },
  { role: 'Base de données', name: 'Neon, Inc.', address: 'États-Unis (région de la base à préciser selon votre console Neon)' },
] as const

export const missingPublisherFields = (): string[] =>
  (Object.entries(PUBLISHER) as [string, string][]).filter(([k, v]) => k !== 'updated' && !v.trim()).map(([k]) => k)
