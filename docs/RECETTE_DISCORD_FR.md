# Recette manuelle sur votre serveur Discord

Ces essais nécessitent votre vrai bot et un serveur de test. Ils ne sont pas considérés comme exécutés par la simple réussite des tests locaux. Faites-les avant l'ouverture au public.

Préparez le propriétaire du serveur, un membre staff et deux comptes de test ordinaires sans permission Administrator. Évitez d'accorder un rôle staff aux comptes qui testent la confidentialité.

## Installation et synchronisation

- [ ] Sur Windows 11, extraire le ZIP dans un chemin contenant des espaces et lancer `INSTALLER_WINDOWS.bat` sans droits administrateur.
- [ ] Vérifier que l'installation conserve un `config.json` et un `.env` déjà présents.
- [ ] Renseigner le bot, son serveur et les intents, puis lancer `DEMARRER_WINDOWS.bat`.
- [ ] Vérifier les catégories, l'ordre des salons et les sept rôles attendus.
- [ ] Vérifier qu'il existe un seul salon central `open-a-ticket` et aucun service Character Advertisement.
- [ ] Vérifier que les salons staff et les journaux sont invisibles aux deux clients.
- [ ] Vérifier que les clients voient les produits mais ne peuvent pas publier dans les salons commerciaux.
- [ ] Redémarrer le bot et relancer une synchronisation : aucun doublon de rôle, catégorie, salon ou panneau.
- [ ] Modifier une description et un prix de test, synchroniser, puis vérifier la mise à jour du même panneau.
- [ ] Ajouter temporairement une nouvelle espèce selon le modèle et vérifier sa création après synchronisation.

## Embeds, boutons et menus

- [ ] Dans chaque salon de vente ou service, vérifier l'embed en anglais et le bouton réellement vert et cliquable.
- [ ] Contrôler les ressources Dedi, Dino Lines, bases, blueprints, kits, Tek Items, boss et note runs.
- [ ] Contrôler les cinq menus du salon central et leur correspondance avec les options attendues.
- [ ] Vérifier l'emoji 🪙 et la règle **All prices are fixed and non-negotiable.**
- [ ] Vérifier que tout tarif non choisi affiche **Contact Staff**, sans statistique ou stock inventé.
- [ ] Vérifier les images configurées ; une URL incorrecte ne doit pas exposer de fichier privé.
- [ ] Pour les boss et cartes, valider les informations sur votre version d'ASA et votre cluster ; présenter les offres non confirmées comme demandes d'information, sans promettre leur disponibilité.

## Confidentialité et déroulement d'une commande

- [ ] Avec le client A, cliquer sur **Buy Element Dust**. Vérifier que le ticket identifie Element Dust.
- [ ] Vérifier que A et le staff accèdent au ticket, et que le client B ne peut ni le voir ni le lire.
- [ ] Indiquer quantité, serveur et détails de commande ; vérifier que le staff les reçoit.
- [ ] Prendre en charge le ticket avec le compte staff. Vérifier l'identité de la personne assignée.
- [ ] Vérifier qu'un client ne peut pas utiliser les commandes ou contrôles réservés au staff.
- [ ] Marquer la commande comme terminée ; vérifier l'état enregistré et les notifications prévues.
- [ ] Fermer le ticket et confirmer ; vérifier `data/transcripts/`, la confidentialité du journal, le renommage en `closed-...` et la perte d'accès du client. Le salon fermé reste conservé pour le staff.
- [ ] Vérifier que le transcript conserve le texte et les liens des pièces jointes ; les fichiers joints eux-mêmes ne sont pas archivés.
- [ ] Essayer les tickets General Orders, Boss Fights, Note Runs, Buy Base, Sell Base et Base Advertisement.
- [ ] Essayer les services Middleman, Become a Seller, Report a Scammer et Staff Inquiries.
- [ ] Vérifier qu'un signalement n'est pas diffusé dans les salons publics et qu'un membre portant uniquement le rôle Seller ne voit ni le ticket de signalement ni son transcript.

## Résistance au spam et redémarrage

- [ ] Cliquer deux fois rapidement sur le même produit : le système doit éviter deux tickets ouverts identiques.
- [ ] Tester les limites de fréquence et du nombre de tickets définies dans la configuration.
- [ ] Ouvrir un ticket, arrêter le bot proprement, le redémarrer, puis tester les boutons de l'ancien ticket.
- [ ] Après redémarrage, tester un bouton d'achat et un menu publiés avant l'arrêt.
- [ ] Vérifier que le suivi des commandes et les panneaux retrouvent leurs identifiants persistants.
- [ ] Exécuter `main.py --backup`, puis vérifier la sauvegarde de `data/shop.sqlite3` dans `data/backups/` et sa lecture sur une copie locale, sans lancer une deuxième instance sur le même serveur.

## Ouverture publique

- [ ] Remplacer le nom et les visuels d'exemple par ceux de votre boutique.
- [ ] Renseigner vos conditions, votre politique de livraison et les moyens de paiement réellement acceptés.
- [ ] Faire vérifier les stocks, caractéristiques et tarifs par un responsable.
- [ ] Ne publier comme disponibles que les offres réellement assurées sur votre version d'ASA et votre cluster.
- [ ] Garder une sauvegarde privée et une procédure de redémarrage connue du staff.
- [ ] Confirmer que le PC ou l'hébergement restera connecté et que le bot n'utilise pas Administrator.
