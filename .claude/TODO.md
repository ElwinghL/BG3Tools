# Chantier immédiat / prioritaire

- Mods installés par glisser-déposer sur le mod manager (ni Nexus, ni Mod.io) : tenter de les relier à l'une des deux sources
  - Matching par nom de fichier/mod
  - Matching par hash du .pak
  - Si aucun match automatique, demander à l'utilisateur d'indiquer la source (lien Nexus/Mod.io)
- Le texte des doublons supprimes doit etre codifier pour etre plus lisible
- Priorisation Nexus / Mod.io (règle unique) :
  - Si Mod.io propose une version plus récente que celle de Nexus, on privilégie Mod.io, avec (un)subscribe auto si besoin
  - Gérer les erreurs d'écriture lors d'une mise à jour via Mod.io (fréquentes en jeu) ; si l'écriture réussit sans passer par un dl d'archive, on change l'origine du mod vers modio
  - Process de vérification de version entre archives locales et Nexus
- Téléchargements en parallèle :
  - Mod.io ne pose aucune question → téléchargeable en parallèle de Nexus sans souci
  - Nexus : pendant qu'un DL tourne, préparer les wizards suivants (max ~6 threads de DL)
  - Console dédiée avec barres de progression par thread de DL, sous la console principale
- Outil standalone de vérification/validation des .pak — équivalent léger et rapide de la partie "check des .pak" de divinity.exe (pas la génération de modsettings.lsx ni le lancement du jeu)
  - L'outil actuel, pour de la lecture uniquement, timeout beqaucoup
- Rename des merge de branche precedents pour suivre la convention de notation (nom de la branche en message de commit)
- Par profils, on compte le nombre d'utilisation de chaques boutons, outils... et autres joyeusetes de notre appli, et on ajoute trois boutons de quick action en haut pour les trois actions les plus utilisees par le profil

# Chantier annexe — page de build de classes (à faire avant V2/V3/V4)

- Le build est exportable
- Rendre le générateur de doc autonome, indépendant du profil et des mods
- Dans le profil, créer une page web qui permet de concevoir son build (classes / sous-classes installées) jusqu'au niveau 20
- Le build se crée et se visualise sous forme de graph mermaid
- À chaque niveau : afficher ce qu'on gagne, et permettre de changer de classe (jamais deux fois la même classe dans un même build ; on peut juste continuer la progression d'une classe déjà prise)
- Utiliser le standalone divinity, ou en créer un dédié, pour lister les détails des classes / sous-classes

# Chantier moyen V2

- On release une version indépendante du mod (wheel ?)

# Gros chantier V3 ou V4

- Alternative : GUI Python indépendant de la console, pour Linux et Windows, avec les fonctionnalités citées plus haut
- Version alternative de l'outil : serveur web local permettant de visualiser et d'agir via le navigateur (on pourra avoir le visuel façon parchemin sur nos consoles par exemple)
  - Échange de fichiers .pak et de profils par socket, sécurisé par clé + fichier d'autorisation (façon ssh)
  - Utilisation du standalone divinity pour faire du check de versionning en amont du lancement du jeu, par socket

# Taches faites

- Téléchargement depuis un fichier texte : afficher une progression X/Y (ligne X sur total Y) — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/af7fe06eea6cb87b4b9aa2c449ad5e0bc92f14c7)
- Enrichir le message "déjà un hardlink" avec plus d'infos utiles (mod concerné, chemin, etc.) — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/f5b953f99b834ba980ee92dc1cc7b4fdbc427d69)
- Alignement de colonne dans la Console Tâche : élargir le compteur de .pak extraits à 2 digits — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/9cd50efa2b76a9817ac1108140f12d92446302d7)
- Ne pas dupliquer les archives / les .pak déjà présents (dans les archives ou dans mods) lors d'une installation par extraction vers mods — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/b938485)
- Fix des décalages d'alignement de texte dans l'UI/console de l'outil (pas in-game), causés par certains mods — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/60d2501)
- Ctrl+Maj+C ne marche pas sur le texte highlight — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/1585d85)
- Ajouts de tests pour empecher les regressions — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/0698e3d)
- Le changement de profil enleve tous les hardlinks deja en place (+ fichier de suivi des hardlinks par profil) — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/3532765)
- Afficher une progression claire pour l'outil Archives orphelines (lecture des UUID de .pak déployés + vérification par archive) — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/dd6d374)
- Fix des doublons d'archives mod.io (download_subscribed_modio_mods ne vérifiait pas les dossiers déjà installés) + nettoyage intégré des doublons dans \_installees lors de "télécharger les mods"/"extraire vers Mods/" — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/e6d9578)
- Vue par onglets (Tâches/Outils/Web) pour les consoles, à la place de l'empilement vertical — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/a5baf81)
- Import de profil : vérification des fichiers manquants + garde-fou de version (avertissement, pas de blocage) — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/26463ad)
- Mods avec ZIP imbriqués : wizard de sélection pour choisir lesquels garder/extraire — [merge](https://git.clementleboeuf.ovh/elwinghit/BG3Tools/commit/e819a64)
