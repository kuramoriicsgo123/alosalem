# Mécaniques ARK et limites de vérification

Le catalogue distingue la programmation du bot des caractéristiques des offres que le propriétaire doit valider. Toutes les quantités, statistiques, récompenses et disponibilités doivent correspondre à ce que votre boutique livre réellement. Les pages ARK couvrent parfois simultanément Survival Evolved (ASE) et Survival Ascended (ASA) : ne recopiez pas les mécaniques d'une version vers l'autre.

La page [Ascension du wiki communautaire officiel ARK](https://ark.wiki.gg/wiki/Ascension) a pu être consultée le **13 octobre 2026**. La reprise de la recherche le 14 octobre a été bloquée par le réseau et la demande d'accès supplémentaire a été interrompue. La vérification complète de chaque page de boss et de chaque liste d'engrammes Tek reste donc inachevée. Les panneaux conservent explicitement les réserves correspondantes ; aucun tarif ou déblocage inconnu n'est garanti.

## Points retenus de la source consultée

- **Overseer :** ascension de The Island après la Tek Cave ; les trophées des boss de l'île servent à l'accès. L'ascension et la vente d'un combat Broodmother/Megapithecus/Dragon sont deux offres différentes.
- **Manticore :** la source décrit une ascension de Scorched Earth avec des difficultés Gamma, Beta et Alpha. Il serait incorrect d'affirmer sans distinction qu'il ne donne jamais de niveaux supplémentaires.
- **Rockwell :** ascension d'Aberration, avec progression du niveau maximal selon la difficulté.
- **King Titan :** le passage ASA décrit des gains de **+5 / +10 / +15** selon Gamma/Beta/Alpha et la cinématique correspondante. Le gain Alpha est un total de 15 pour cette ascension, pas 5 + 10 + 15. Ne réutilisez pas la règle historique ASE « aucun niveau » pour cette version ASA.
- **Lost Queen :** la source situe l'ascension sur **Lost Colony** et décrit la mission **Red-Handed**, contre **Lost King et Lost Queen**. Elle mentionne des niveaux supplémentaires selon la difficulté et un **Gigadesmodus Egg Sac**. Une vente présentée comme un simple kill de Lost Queen ne doit pas promettre automatiquement l'ensemble de ces récompenses.
- La source consultée comporte également des sections Genesis: Part 1 et Astraeos. Cela ne suffit pas à certifier chaque récompense, chaque liste d'engrammes ou chaque condition de serveur pour les offres du catalogue.

## Informations encore à compléter

| Offre | Éléments restant à vérifier avant une vente ferme |
| --- | --- |
| Master Controller | Conditions précises de l'implémentation ASA, engrammes, missions et éligibilité du joueur |
| Rockwell, Manticore, Overseer, King Titan | Listes Tek exactes par difficulté, autres récompenses et conditions sur le build/serveur vendu |
| Lost Queen | Difficultés exactes de l'offre, gains par palier, déroulement complet de la mission et liste Tek |
| Kraken, Nunatak | Identification de l'encounter exact, carte et version/mod, difficultés réellement proposées, récompenses et niveaux |
| Island Bosses | Listes Tek et butin exacts par boss et difficulté ; l'ascension Overseer reste distincte |
| Ragnarok Boss | Composition actuelle de l'arène ASA et récompenses ; ne pas supposer qu'elle correspond exactement à l'ancienne arène ASE |
| Moeder | Conditions de la mission ASA, liste des récompenses et engrammes ; aucune ascension supplémentaire promise |

Les noms des salons demandés sont présents, mais les services non validés sont affichés comme des demandes d'information avec confirmation staff. Les prix des paliers non identifiés restent des demandes générales, sans inventer Gamma/Beta/Alpha. Aucun boss n'est présenté comme donnant universellement +15 niveaux.

Les dinosaures n'ont aucune statistique inventée. Reapers et Rhyniognatha sont décrits avec un service d'acquisition et non comme une paire reproductrice classique garantie. Renseignez les valeurs réelles dans `products.json` et les montants acceptés dans `prices.json`, puis exécutez `/shop_sync`. Les prix tiers documentés dans `RECHERCHE_PRIX_FR.md` ne constituent pas une preuve de mécanique de jeu.
