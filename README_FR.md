# Boutique Discord ARK: Survival Ascended — installation Windows 11

Ce programme prépare votre serveur Discord : rôles, catégories, salons, présentations en anglais, vrais boutons verts et tickets privés. Chaque bouton d'achat ouvre un ticket correspondant au produit choisi. Les prix non renseignés affichent **Contact Staff** et aucun paiement n'est encaissé automatiquement.

Vous devez créer votre serveur Discord, créer l'application bot et l'inviter vous-même. Ce dossier ne contient aucun accès à votre compte. Le programme configure ensuite le serveur auquel vous avez donné accès au bot. Il s'agit d'une identité indépendante ; aucun logo, visuel ou tarif non vérifié de Derek's Shop n'est repris comme officiel.

Les contrôles automatiques locaux vérifient le code et la configuration. La connexion réelle, les permissions et les interactions doivent être validées sur votre serveur avec votre bot. Les fichiers `.bat` sont fournis pour Windows 11 ; une validation réalisée sous Linux ne constitue pas un essai sur Windows.

Pour le premier démarrage : **extrayez le ZIP → installez Python → lancez `INSTALLER_WINDOWS.bat` → créez et invitez le bot → renseignez `config.json` et `.env` → lancez `DEMARRER_WINDOWS.bat`**. Les étapes ci-dessous expliquent chaque action. Le nom provisoire **Your ASA Shop** se remplace dans `shop_name` ; aucun nom ou logo personnel n'est inventé.

## 1. Préparer le dossier et Python

1. Téléchargez le ZIP et faites **clic droit → Extraire tout**. Ne lancez rien depuis l'aperçu du ZIP.
2. Placez le dossier dans un emplacement personnel, par exemple `C:\Users\VotreNom\Documents\ASA-Shop`. Évitez les dossiers publics et les synchronisations qui pourraient partager vos secrets.
3. Installez **Python 3.12**, recommandé, depuis <https://www.python.org/downloads/windows/>. Python 3.11 ou plus récent est nécessaire. Cochez **Add python.exe to PATH** pendant l'installation.
4. Double-cliquez sur `INSTALLER_WINDOWS.bat`. Aucun lancement en administrateur n'est nécessaire. Une connexion Internet est nécessaire pour télécharger les dépendances.

L'installateur crée `.venv`, installe les versions indiquées dans `requirements.txt`, copie les exemples vers `config.json` et `.env` **uniquement si ces fichiers n'existent pas**, puis vérifie les données sans se connecter à Discord. Vous pouvez le relancer sans remplacer votre configuration.

Dans l'Explorateur Windows, activez **Affichage → Afficher → Extensions de noms de fichiers**. Le fichier secret doit s'appeler `.env`, pas `.env.txt`. Ouvrez les fichiers de configuration avec le Bloc-notes ou un éditeur de texte et enregistrez en UTF-8.

## 2. Créer votre serveur Discord

1. Ouvrez Discord et cliquez sur le **+** dans la liste des serveurs.
2. Choisissez **Créer le mien**, puis donnez le nom de votre boutique.
3. Commencez de préférence avec un serveur vide. Le programme ne supprime pas vos salons personnels pour faire de la place.
4. Dans **Paramètres utilisateur → Avancés**, activez le **Mode développeur**.
5. Faites un clic droit sur l'icône de votre serveur puis **Copier l'identifiant du serveur**. Conservez cet identifiant public pour `guild_id`.

## 3. Créer le bot dans le Developer Portal

1. Ouvrez <https://discord.com/developers/applications> et connectez-vous à Discord.
2. Cliquez sur **New Application**. Donnez un nom à votre bot et acceptez les conditions.
3. Dans **General Information**, copiez **Application ID**. Cet identifiant public va dans `application_id`.
4. Ouvrez **Bot**. Si nécessaire, créez le bot. Personnalisez son nom et son avatar dans cette page.
5. Dans **Privileged Gateway Intents**, activez **Server Members Intent** pour les messages d'accueil et **Message Content Intent** pour conserver le contenu des conversations dans les transcripts. **Presence Intent** est inutile.
6. Cliquez sur **Reset Token** si nécessaire, puis copiez le token uniquement dans votre fichier local `.env`.

Le fichier `.env` doit contenir une ligne de cette forme, avec votre propre valeur après le signe `=` :

```dotenv
DISCORD_TOKEN=COLLEZ_VOTRE_TOKEN_ICI
```

Le token est le mot de passe du bot. Ne le mettez jamais dans `main.py`, `config.json`, une capture d'écran, un ticket, un dépôt Git, un ZIP partagé ou une conversation. `.env` est ignoré par Git. Si le token a été partagé, réinitialisez-le immédiatement dans le Developer Portal, remplacez-le localement et redémarrez le bot. Une variable d'environnement `DISCORD_TOKEN` peut remplacer le fichier `.env`.

Pour un bot dépassant les seuils de vérification de Discord, les intents privilégiés peuvent nécessiter une approbation de Discord. Un petit serveur de boutique peut commencer avec les interrupteurs du portail.

## 4. Renseigner la configuration

Ouvrez `config.json`. Remplacez au minimum :

- `guild_id` par l'identifiant de votre serveur, **sans guillemets** ;
- `application_id` par l'identifiant de l'application, **sans guillemets** ;
- `shop_name` par votre nom de boutique.

Les identifiants exemples à `0` permettent la vérification locale mais ne permettent pas une connexion à votre vrai serveur. Respectez le format JSON : guillemets doubles pour les textes, aucune virgule après le dernier élément, pas de commentaires. N'ajoutez jamais le token à ce fichier.

Les paramètres visuels et les fichiers du catalogue sont décrits plus bas. Vous pouvez effectuer ces personnalisations après le premier démarrage.

## 5. Inviter le bot avec les permissions nécessaires

Dans le Developer Portal, ouvrez **OAuth2 → URL Generator**. Sélectionnez les scopes **bot** et **applications.commands**, puis les permissions suivantes :

| Permission du bot | Utilisation |
| --- | --- |
| Manage Channels | Créer les catégories, salons et tickets ; gérer leurs accès |
| Manage Roles | Créer les rôles de la boutique et gérer les permissions des salons |
| View Channels | Voir les panneaux et tickets qu'il gère |
| Send Messages | Publier les panneaux et répondre aux tickets |
| Embed Links | Afficher les présentations de produits |
| Attach Files | Joindre les transcripts |
| Read Message History | Retrouver les panneaux et exporter les tickets |

**Ne cochez pas Administrator.** Pour ces permissions, la valeur numérique est `268553232`.

Vous pouvez aussi ouvrir un terminal dans le dossier et obtenir le lien calculé depuis `application_id` :

```powershell
.\.venv\Scripts\python.exe main.py --invite-url
```

Ouvrez le lien généré, choisissez **votre serveur** et autorisez le bot. Cette étape demande un compte autorisé à gérer ce serveur. Si le portail affiche des réglages d'installation, activez l'installation sur serveur (**Guild Install**).

Dans **Paramètres du serveur → Rôles**, placez le rôle propre au bot assez haut pour qu'il soit **au-dessus de tous les rôles qu'il doit créer ou gérer**. Après création, conservez ce rôle au-dessus des rôles de la boutique, y compris `👑 Owner`. Le propriétaire réel du serveur garde ses droits Discord. Le programme ne distribue pas automatiquement les rôles privilégiés à des membres : attribuez-les vous-même à des personnes de confiance.

Ne donnez pas de permissions supplémentaires à `@everyone` et ne rendez pas publiques les catégories staff ou les tickets. Vérifiez les accès avec un compte de test ordinaire avant d'ouvrir la boutique.

## 6. Démarrer la boutique

Double-cliquez sur **DEMARRER_WINDOWS.bat**. Le programme vérifie vos fichiers, se connecte et synchronise la boutique. La première création peut prendre quelques minutes, car les appels respectent les limites de Discord.

Gardez la fenêtre ouverte. Un bouton Discord ne peut ouvrir un ticket que lorsque le bot est connecté. Pour arrêter proprement, utilisez **Ctrl+C** et attendez la fin du programme.

Le lanceur utilise `--setup` à chaque démarrage. La synchronisation retrouve les rôles, salons et panneaux enregistrés et met à jour leurs contenus ; une relance normale ne doit pas créer de doublons. Il n'existe qu'un salon central `🎫・open-a-ticket`. Conservez les données locales : elles relient le bot aux messages, tickets et commandes déjà créés.

Les commandes principales sont :

```powershell
# Vérifier la configuration sans connexion ni token
.\.venv\Scripts\python.exe main.py --check

# Synchroniser la boutique, puis laisser le bot connecté
.\.venv\Scripts\python.exe main.py --setup

# Connecter le bot pour utiliser les panneaux déjà installés
.\.venv\Scripts\python.exe main.py
```

Utilisez une seule instance du programme avec le même token et les mêmes données. Ne lancez pas simultanément le bot sur votre PC et un hébergeur.

## 7. Utiliser les tickets et les commandes

Le salon central contient cinq menus : **General Orders**, **Boss Fights**, **Note Runs**, **Base Services** et **Other Services**. Un bouton vert dans un salon de vente ouvre directement le produit concerné, sans repasser par les menus.

Le clic affiche un formulaire avec la quantité ou difficulté, la carte et le type de serveur, puis les détails de commande. L'envoi de ce formulaire crée le ticket privé et présente le produit demandé. **Claim order** permet au staff de prendre en charge la commande ; **Mark completed** enregistre sa réalisation sans fermer le ticket. Le client ou le staff peut utiliser **Close ticket**, puis **Confirm close**. Les autres clients ne doivent pas pouvoir lire le salon. Par défaut, un client dispose au maximum de trois tickets actifs, avec un délai de trente secondes entre créations et un seul ticket actif par produit.

La fermeture enregistre d'abord un transcript, puis renomme le salon `closed-00001` et retire l'accès du client. Le salon reste accessible en lecture au staff ; il n'est pas supprimé automatiquement. Les transcripts se trouvent dans `data/transcripts/` et sont joints au journal staff approprié quand les permissions et la taille le permettent. Si l'export local échoue, le ticket est conservé. Après sauvegarde et vérification des transcripts, le propriétaire peut supprimer manuellement les anciens salons fermés pour libérer la capacité du serveur.

Les interactions utilisent des identifiants persistants : les boutons fonctionnent après redémarrage si le bot tourne, si sa configuration reste compatible et si ses données sont conservées.

Les commandes Discord `/shop_sync`, `/shop_status` et `/shop_announce` sont destinées aux responsables autorisés. Commencez à saisir leur nom dans Discord pour voir leurs paramètres. `/shop_sync` applique les modifications des fichiers JSON aux panneaux ; `/shop_announce` publie une annonce. Les nouveaux droits ou commandes peuvent mettre un court délai à apparaître dans le client Discord.

Une commande terminée est un état enregistré par votre staff. Le bot ne vérifie ni le paiement ni la livraison dans le jeu. Vérifiez vous-même le paiement avant toute livraison. Il ne crée pas de faux avis, de fausses ventes, de fausses statistiques de fréquentation ou de faux stocks.

## 8. Personnaliser les produits, prix et visuels

Tous les contenus publics de boutique sont en anglais. Conservez cette langue dans vos modifications. Les messages commerciaux incluent **All prices are fixed and non-negotiable.** Un prix non renseigné vaut **Contact Staff** : le staff doit alors définir et confirmer un tarif fixe avant la commande.

- `config.json` contient le nom, les paramètres visuels et les réglages du bot ;
- `products.json` contient les descriptions, caractéristiques, disponibilités et informations propres aux produits ;
- `prices.json` regroupe les tarifs ;
- `structure.json` contient les textes d'information, règles, moyens de paiement à compléter et l'organisation des catégories ;
- `config.example.json` sert de référence sans secrets.

Pour modifier un produit, cherchez son identifiant dans `products.json`, modifiez ses champs puis son entrée dans `prices.json`. Gardez les identifiants stables : ils servent à reconnaître les boutons et les commandes. Vérifiez avec `--check`, puis utilisez `/shop_sync` ou redémarrez avec le lanceur Windows.

Dans `prices.json`, remplacez uniquement le `null` du tarif souhaité par votre montant numérique, par exemple `12.5` pour **12,50 €**. Cet exemple explique le format ; il ne constitue pas une recommandation de prix. N'écrivez pas `"12,50 €"` ni `"Contact Staff"` : laissez `null` quand le prix reste à choisir. La clé `currency` accepte `EUR`, `USD` ou `GBP`. Chaque produit possède les entrées **Official 1x**, **Small Tribes** et **PvE**, puis les variantes proposées.

Les ressources Dedi proposent **1 Dedi**, **5 Dedis**, **10 Dedis** et **Custom Quantity**. Les tarifs se déclinent selon **Official 1x**, **Small Tribes** et **PvE**. Une quantité en Dedi doit être confirmée selon les règles de stockage et de stack du serveur. **ADV** désigne **Advanced Rifle Bullets**, dans le catalogue Dedi.

Les Dino Lines laissent à compléter les niveaux, HP, Melee Damage, mutations, couleurs, prix unitaires et prix du breeding pair. Les caractéristiques affichées sont les valeurs `value` de la liste `fields` : modifiez les champs **Level**, **Health (HP)**, **Melee Damage**, **Mutations** et **Available Colors**. Ne publiez que vos statistiques réelles. Pour une nouvelle espèce, copiez une entrée de la même famille dans `products.json`, donnez-lui un `id` unique, gardez `category` à `dino-lines`, adaptez `channel`, `title`, `description`, `button_label`, `fields` et `availability`, puis ajoutez une entrée de même `id` dans `prices.json`. Son salon et son bouton direct sont créés à la synchronisation ; le menu général **Dino Lines** reste un accès global à cette famille. Vous n'avez pas à réécrire le bot.

Pour une base, renseignez dans `fields` sa référence, carte, type de serveur, mode PvP/PvE, description, structures incluses et liens vers les captures ; renseignez aussi `availability` et ses tarifs. Le champ `image_url` affiche l'image principale sous l'embed. Pour plusieurs captures, placez leurs liens HTTPS dans le champ **Screenshots** ; les liens restent consultables. Le service **Base Advertisement** propose **One-Time Advertisement**, **5 Posts Package** et **10 Posts Package**, avec des prix configurables. Le programme reçoit les demandes ; le staff publie les annonces convenues et suit le nombre de publications. Aucun service **Character Advertisement** n'est installé.

Le thème utilise des embeds avec accents rouges et de vrais boutons Discord verts. Dans `config.json`, `accent_color` définit l'accent hexadécimal, `logo_url` l'image de marque et `banner_url` la bannière par défaut. Le `image_url` d'un produit remplace cette bannière sur son panneau. Discord impose la couleur du fond selon le thème choisi par chaque utilisateur : le bot ne peut pas rendre l'interface Discord entière sombre. Les images et bannières utilisent des URL HTTPS publiques directes vers vos propres images. Évitez les liens vers une page de partage privée ou qui expire. Le nom et l'avatar du compte bot se changent dans le Developer Portal.

L'emoji monétaire par défaut est le vrai caractère **🪙**, visible dans les embeds et messages. Pour un emoji Discord personnalisé autorisé et accessible au bot, utilisez son format Discord complet, par exemple `<:coin:123456789012345678>`, dans `coin_emoji` de `config.json`. Le texte seul `:coin:` ne garantit pas un rendu emoji.

Les prix publics de boutiques tierces ne valent pas automatiquement pour vos serveurs, plateformes ou quantités. Les montants non confirmés restent **Contact Staff**. Les informations de recherche et leurs limites sont livrées séparément ; aucune estimation n'est présentée comme tarif officiel de Derek's Shop.

## 9. Permissions et confidentialité

Le bot crée les rôles `👑 Owner`, `🛡️ Admin`, `🔨 Moderator`, `🛒 Seller`, `💎 VIP`, `⭐ Customer` et `🤖 Bots`. Il n'attribue pas automatiquement les rôles de direction à des clients. Un rôle portant le nom Owner ne remplace pas le propriétaire réel du serveur Discord.

Les membres consultent les panneaux sans pouvoir les modifier. Les salons communautaires servent aux échanges. Les tickets sont accessibles à leur client, au bot et aux rôles staff prévus. Les rôles ayant déjà **Administrator** dans votre serveur peuvent voir les salons privés : Discord leur donne cet accès indépendamment du bot.

Les journaux et transcripts restent réservés au staff. Les tickets **Report a Scammer** excluent le rôle Seller. Si le journal de tickets est visible des vendeurs, le transcript d'un signalement reste uniquement dans le dossier local privé : il n'y est pas envoyé. Les transcripts peuvent contenir des identifiants, messages de clients et détails de commande. Ils enregistrent les messages encore accessibles au moment de la fermeture, et les pièces jointes sous forme de liens : les fichiers joints ne sont pas téléchargés et leurs liens peuvent expirer. Les messages supprimés ne sont pas récupérés. Limitez les accès, protégez votre dossier local et vos sauvegardes, et définissez une durée de conservation adaptée à votre boutique. Évitez de demander des mots de passe ou des coordonnées de paiement sensibles dans les tickets.

Avant l'ouverture publique, suivez [la liste de contrôle Discord](docs/RECETTE_DISCORD_FR.md), en particulier les essais de confidentialité avec deux clients distincts.

## 10. Sauvegarder et déplacer le bot

Sauvegardez `config.json`, `products.json`, `prices.json`, `structure.json`, votre `.env` dans un emplacement privé et le dossier de données indiqué par `data_dir`. Par défaut, **`data/shop.sqlite3`** contient les identifiants Discord, les tickets et le suivi des commandes ; **`data/transcripts/`** contient leurs historiques exportés. Ne partagez jamais cette sauvegarde comme ZIP de distribution.

Une copie brute d'une base SQLite en cours d'écriture peut être incomplète. Cette commande crée une sauvegarde cohérente de la base, contrôle son intégrité et affiche son emplacement dans `data/backups/` ; elle fonctionne aussi pendant que le bot tourne :

```powershell
.\.venv\Scripts\python.exe main.py --backup
```

Cette commande sauvegarde **la base uniquement** : copiez aussi les JSON, `.env` et transcripts en privé. Pour une copie manuelle du dossier complet, arrêtez d'abord le bot avec **Ctrl+C**. Ne supprimez pas les éventuels fichiers SQLite `-wal` et `-shm` après une interruption. Pour restaurer, arrêtez le bot, conservez une copie du dossier actuel et placez votre sauvegarde cohérente sous le nom `data/shop.sqlite3` dans un dossier de données propre, avec les transcripts associés. Vérifiez la restauration sur une copie avant de reprendre le service.

Pour migrer vers un autre PC ou un hébergeur, arrêtez l'ancienne instance, transférez les fichiers de configuration et données en privé, réinstallez les dépendances, puis lancez une seule nouvelle instance. Ne copiez pas `.venv` entre deux systèmes : recréez-le avec l'installateur ou `python -m venv .venv`.

## 11. Garder le bot en ligne

Sur Windows, le PC doit rester allumé, connecté à Internet et sans mise en veille. Fermer la fenêtre, arrêter le PC ou suspendre Windows rend les interactions indisponibles. Le programme doit rester lancé ; il ne déploie pas automatiquement un hébergement permanent.

Pour une disponibilité continue, utilisez un VPS ou un hébergeur capable d'exécuter durablement Python 3.11 ou plus récent avec stockage persistant. Conservez les secrets dans les réglages sécurisés de l'hébergeur et utilisez un superviseur de processus. Le bot utilise des connexions sortantes vers Discord ; aucun port entrant ni redirection de votre box ne sont nécessaires.

Sous Linux, dans le dossier du projet :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n config.example.json config.json
cp -n .env.example .env
# Renseignez les fichiers localement avant la connexion.
.venv/bin/python main.py --check
.venv/bin/python main.py --setup
```

Ces commandes servent aussi à préparer un environnement cloud. Utilisez le checkout fourni dans la tâche : chaque tâche cloud est déjà isolée et ne nécessite pas de worktree Git supplémentaire.

## 12. Dépannage

| Symptôme | Action |
| --- | --- |
| Python introuvable | Installez Python 3.12 depuis python.org avec l'option PATH, puis relancez l'installateur |
| L'installation échoue en téléchargeant les dépendances | Vérifiez Internet, le proxy et les certificats de confiance ; conservez TLS et la vérification des téléchargements |
| Fichier JSON invalide | Corrigez la ligne indiquée ; vérifiez guillemets et virgules, puis exécutez `--check` |
| Token manquant ou connexion refusée | Vérifiez `.env`, son extension et `DISCORD_TOKEN`. Un Application ID n'est pas un token |
| Le bot réclame un intent | Activez Server Members Intent et Message Content Intent dans la page Bot du portail |
| Serveur introuvable | Vérifiez `guild_id` et invitez le bot sur ce serveur avec le bon compte |
| Missing Permissions / Forbidden | Vérifiez les permissions de l'invitation, les exceptions de salon et la position du rôle du bot |
| Le bouton affiche une erreur d'interaction | Vérifiez que le bot tourne ; regardez la console ; vérifiez les permissions et synchronisez les panneaux |
| Les produits affichent encore l'ancien prix | Enregistrez le JSON, vérifiez avec `--check`, puis `/shop_sync` |
| Un panneau ou salon a été supprimé manuellement | Relancez une synchronisation et vérifiez les journaux ; conservez la base de données |
| Un client peut voir un autre ticket | Fermez temporairement les nouvelles commandes et corrigez les rôles Administrator ou exceptions de permissions ; refaites les tests avec un compte sans rôle staff |
| Le contenu des transcripts est absent | Activez Message Content Intent, redémarrez et vérifiez View Channel / Read Message History ; les messages supprimés ne peuvent pas être reconstruits |

Ne publiez pas vos fichiers de données ou votre `.env` pour demander de l'aide. Partagez uniquement le message d'erreur utile après avoir masqué les informations privées.

### Commandes et précisions complémentaires

`/shop_orders` affiche les dix dernières commandes terminées aux responsables, en réponse privée. Les rôles Owner et Admin gèrent la boutique via les contrôles du bot ; ils ne reçoivent pas automatiquement de pouvoirs d’administration globale du serveur. Les rôles de boutique déjà existants avec Administrator doivent être corrigés ou renommés avant leur adoption.

Pour utiliser une pièce personnalisée, importez cet emoji dans **ce même serveur**, puis configurez sa forme `<:coin:IDENTIFIANT>`. La pièce standard 🪙 fonctionne sans permission d’emoji externe. Pour changer de serveur, choisissez également un nouveau `data_dir` : les données d’un serveur ne doivent pas être réutilisées pour un autre.

Les champs structurés `stats` des dinosaures sont également pris en charge : une valeur renseignée remplace le champ correspondant (Level, HP, Melee, Mutations ou Colors). Gardez `null` pour conserver le texte de `fields`. Les listes `screenshots` acceptent jusqu’à cinq URLs HTTPS : elles deviennent des liens visibles, et la première capture sert d’image si `image_url` est vide.

Les versions exactes des dépendances, directes et indirectes, figurent dans `requirements.lock`, inclus par `requirements.txt`. Le relevé des prix tiers est dans [RECHERCHE_PRIX_FR.md](RECHERCHE_PRIX_FR.md) ; les limites de vérification et la recette manuelle figurent dans `docs/`.
