# Outils tiers

Liste des outils tiers utilisés dans ce workspace (non versionnés, voir
`.gitignore`) et de leur dépôt source d'origine.

| Outil                       | Dossier local                                                     | Dépôt source                                                                                   |
| --------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| BG3 Load Order Optimizer    | `Tools/BG3-Load-Order-Optimizer/`                                 | https://github.com/Nemix3D/bg3-load-order-optimizer                                            |
| LSLib                       | `Tools/ExportTools/`                                              | https://github.com/Norbyte/lslib                                                               |
| Para Tool                   | `Tools/Para-Tools/`                                               | https://github.com/Paramonov86/Para_Tool                                                       |
| BG3 Mod Manager             | `Tools/BG3ModManager_Latest/`                                     | https://github.com/laughingleader/bg3modmanager                                                |
| BG3 Script Extender (BG3SE) | `Tools/BG3 Script Extender/`                                      | https://github.com/ElwinghL/bg3se (fork de https://github.com/Norbyte/bg3se) |
| Native Mod Loader           | — (à télécharger manuellement, DLL non récupérable depuis GitHub) | https://github.com/gottyduke/NativeModLoader / https://www.nexusmods.com/baldursgate3/mods/944 |
| BG3 Compatibility Framework | `Tools/BG3-Compatibility-Framework/`                              | https://github.com/BG3-Community-Library-Team/BG3-Compatibility-Framework                      |
| MoreReactiveCompanions      | — (application de configuration lancée telle quelle, jamais téléchargée dans `Tools/`) | https://www.nexusmods.com/baldursgate3/mods/5447                                               |
| Mod Fixer                   | `Tools/ModFixer/`                                                 | https://github.com/ElwinghL/ModFixer (repackaging propre — technique d'origine : Nexus #141 par figs999, créditant Norbyte/BG3SE) |
| bg3rustpaklib                | `Tools/bg3rustpaklib/`                                            | https://github.com/ElwinghL/bg3rustpaklib                                                      |
| bg3pythonpaklib              | `Tools/bg3pythonpaklib/`                                          | https://github.com/ElwinghL/bg3pythonpaklib                                                    |
| NMCM (Native Mod Configuration Menu) | `Tools/bg3-nmcm/`                                         | https://github.com/ElwinghL/bg3-nmcm-patcher (fork de https://github.com/Luiznunes12/bg3-nmcm, pour y proposer nos patchs — voir `Tools/nmcm_patches/`) / https://mod.io/g/baldursgate3/m/native-mod-configuration-menu |
| Yet Another BG3 Native Mod Loader (autostart) | `Installation BG3/bin/YABG3ML-Autostart/` (hardlink géré via `native_mods_manifest.json`) | https://github.com/MolotovCherry/Yet-Another-BG3-Native-Mod-Loader |

## Yet Another BG3 Native Mod Loader — contrainte registre Proton

Installé le 2026-09-13 via `protontricks 1086940 -c "wine autostart-installer.exe --install"`
(depuis le vrai chemin d'installation du jeu, pas le lien `BG3_Managed`, pour que le
chemin enregistré en registre soit stable). Ça pose deux clés `Image File Execution
Options` (`bg3.exe`, `bg3_dx11.exe`) dans le registre du préfixe Proton de l'AppID
1086940, pointant vers le chemin exact de `bg3_autostart.exe` au moment de
l'installation.

**Ne jamais déplacer `bg3_autostart.exe`/`loader.dll` après coup** sans d'abord lancer
`uninstall.bat` (sinon le jeu refusera de démarrer tant que
`uninstall.bat` n'a pas été relancé — pas de perte de sauvegarde, mais blocage
temporaire). Le pipeline `bg3_mod_tui` ne redéploie ce dossier que si l'archive est
remise manuellement dans `_a_traiter` (elle a été déplacée vers `_installees` après
déploiement), donc rien dans les actions automatiques du TUI ne touche ces fichiers
par erreur — mais toute intervention manuelle sur `BG3_Managed/NativeMods/BG3 Mod
Loader - Autostart.../` ou sur `Installation BG3/bin/YABG3ML-Autostart/` doit passer
par `uninstall.bat` d'abord.
