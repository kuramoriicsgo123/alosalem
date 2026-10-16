# Contrôle qualité de la livraison

Environnement de validation : Linux, Python 3.12.14, discord.py 2.6.4. Les résultats ci-dessous portent sur le programme et ses simulations locales ; ils ne prétendent pas valider un serveur Discord réel.

## Contrôles exécutés

- Installation des dépendances exactes via `requirements.lock`, sans désactiver TLS ; `pip check` ne détecte aucune dépendance cassée.
- Exécution du script réutilisable `scripts/setup_cloud.sh` : installation relançable, configuration vérifiée et suite de tests terminée.
- **51 tests automatiques réussis**, aucun test ignoré : stockage SQLite, concurrence, confidentialité, droits du staff, création et fermeture de tickets, export de transcript et récupération après interruption ; génération des panneaux, commandes et contrôle de configuration.
- Synchronisation testée avec une API Discord simulée : la deuxième synchronisation ne crée aucun doublon ; changement de prix appliqué au panneau existant ; récupération des panneaux depuis leurs marqueurs ; traitement des permissions insuffisantes et identifiants incohérents.
- L'invitation et le contrôle de démarrage couvrent toutes les permissions autorisées **ou interdites** par les exceptions des catégories, salons et tickets, conformément à la documentation Discord. Un test vérifie les deux masques de permissions ; un autre vérifie l'arrêt avant toute modification si un droit requis manque. Le bot conserve ces droits dans ses exceptions personnelles, sans Administrator et sans exception de salon Manage Roles.
- Les refus Discord indiquent l'étape concernée et les codes HTTP/API. Le premier correctif des réactions n'a pas suffi sur le serveur de l'utilisateur ; la reprise avec la liste complète de permissions reste à vérifier sur Discord.
- Boutons de vente de type réel `discord.ButtonStyle.success`, vues persistantes avec identifiants stables et cinq menus dans les limites de Discord.
- Catalogue initial : **11 catégories, 76 salons, 54 panneaux de produits/services et 59 destinations de tickets**, dont cinq accessibles uniquement via les menus. Un seul salon central `open-a-ticket` ; aucun service Character Advertisement.
- Vérification de tous les embeds : tailles de champs et taille totale compatibles avec les limites Discord. Les données inconnues ne deviennent pas de fausses statistiques ou de faux tarifs.
- Sauvegarde d'une base SQLite ouverte en mode WAL, récupération du dernier état validé et contrôle d'intégrité de la copie.
- Téléchargement réussi des distributions binaires de **toutes les dépendances pour Windows x64 / Python 3.12**. Les scripts `.bat` ont été relus et fournis en UTF-8 avec fins de ligne Windows.

Certaines erreurs sont volontairement provoquées dans les tests, par exemple un refus Discord ou un échec de transcript. Leur journal peut contenir `closure failed` : le test vérifie précisément que le ticket est préservé et ses permissions restaurées. Le résultat global attendu reste `OK`.

## Vérifications encore nécessaires sur votre serveur

Le token n'a pas été fourni et aucun accès direct au serveur Discord n'a été utilisé pour ces tests. Les captures de l'utilisateur montrent une installation Windows et une création partielle jusqu'à `available-stock` ; elles ne valident pas encore la synchronisation complète ni les tickets. Les scripts Windows n'ont pas été exécutés sur une machine Windows par l'agent. Suivez [RECETTE_DISCORD_FR.md](RECETTE_DISCORD_FR.md) après invitation du bot : vérification avec deux comptes clients, contrôle staff, achat direct, fermeture, transcript, redémarrage et synchronisation.

Les permissions Discord du propriétaire réel et des comptes disposant d'Administrator contournent les restrictions de salons : ne donnez ces privilèges qu'à des responsables de confiance. Le programme n'attribue pas Administrator aux rôles créés.

Les pièces jointes des tickets sont conservées sous forme de liens dans les transcripts ; ces liens Discord peuvent expirer. Pour des preuves durables, le staff doit sauvegarder séparément les fichiers utiles. La fermeture archive les salons sans suppression automatique ; surveillez les limites de salons Discord et supprimez manuellement les anciennes archives après vérification des sauvegardes.

La publication de l'environnement cloud et sa restauration dans une nouvelle tâche n'ont pas été exécutées. Les scripts d'installation et instructions de démarrage sont enregistrés dans le brouillon de configuration, à revoir puis publier dans les paramètres de l'environnement.
