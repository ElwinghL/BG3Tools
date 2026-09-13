#!/usr/bin/env bash
# Build ElwinghL/lslib (le fork LSLib, remote de Tools/ExportTools) sur Linux,
# avec le périmètre réduit au strict nécessaire pour Divine (CLI) + la
# lecture/écriture/édition de .pak — voir .claude/TODO.md section 19 et
# le patch 0001-linux-build-pak-only-scope.patch dans ce dossier.
#
# Contexte : le fork upstream (ElwinghL/lslib, branche `main`, actuellement
# figée au commit 551cff1) ne compile pas sous Linux tel quel : il tire
# LSLibNative (.vcxproj C++ natif, GR2/Granny, nécessite MSVC) et le parser
# Osiris Story/Goal (nécessite GPLex 1.2.2 + GPPG 1.5.2, exécutables
# Windows). Ce script applique le patch qui retire ces dépendances (et tout
# ce qui en découle : VirtualTextures, savegames LS/Save) du fichier de
# solution et des .csproj, PUIS build uniquement Divine.csproj (qui référence
# LSLib.csproj) avec le SDK .NET 8.
#
# Le patch N'A PAS été poussé sur le remote ElwinghL/lslib (aucun push vers
# un remote partagé sans autorisation explicite) : il vit uniquement ici,
# dans BG3Tools, en attendant relecture. Pour le pousser soi-même comme
# branche dédiée du fork avant review :
#   cd <clone_fork> && git checkout -b fix/LinuxBuildPakOnlyScope main
#   git apply /chemin/vers/0001-linux-build-pak-only-scope.patch
#   git add -A && git commit -m "..."
#   git push origin fix/LinuxBuildPakOnlyScope   # (à la main, après relecture)
# (`git apply`, pas `git am` : ce dernier échoue à parser ce patch comme un
# mail, cf. commentaire plus bas — la variante `git apply` fonctionne.)
#
# Usage : ./scripts/lslib_fork_linux_build/build_lslib_fork_linux.sh [clone_dir]
#   clone_dir : défaut = un dossier temporaire (mktemp -d), supprimé si le
#               build échoue avant la fin ; passer un chemin existant réutilise
#               un clone déjà présent (le patch n'est réappliqué que s'il ne
#               l'est pas déjà, détecté via le message de commit).
#
# Requiert : git, et soit `dotnet` (SDK 8+) directement disponible, soit un
# conteneur distrobox nommé `bg3tools-dotnet` (cf. .claude/TODO.md pour le
# contexte Bazzite/immutabilité qui a motivé ce conteneur).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="$SCRIPT_DIR/0001-linux-build-pak-only-scope.patch"
FORK_URL="https://github.com/ElwinghL/lslib.git"

CLONE_DIR="${1:-}"
CLEANUP_ON_EXIT=0
if [ -z "$CLONE_DIR" ]; then
    CLONE_DIR="$(mktemp -d -t lslib_fork_linux_build.XXXXXX)"
    CLEANUP_ON_EXIT=1
fi

if [ ! -d "$CLONE_DIR/.git" ]; then
    echo "Clonage de $FORK_URL dans $CLONE_DIR ..."
    command git clone "$FORK_URL" "$CLONE_DIR"
fi

cd "$CLONE_DIR"

# Applique le patch seulement s'il ne l'est pas déjà (idempotent sur un
# clone_dir réutilisé d'un run précédent). `git apply` plutôt que `git am` :
# ce dernier échoue à parser ce patch précis en tant que mail (mbox) — sans
# doute le BOM UTF-8 présent en tête de plusieurs fichiers .cs touchés —
# alors que `git apply --check` l'accepte sans broncher ; on perd juste les
# métadonnées d'auteur/date du commit d'origine, sans conséquence ici.
if ! command git log --oneline | grep -q "trim solution to Divine + pak/resource I/O"; then
    echo "Application du patch de réduction de périmètre ..."
    command git apply "$PATCH_FILE"
    command git add -A
    command git commit -m "Apply fix/LinuxBuildPakOnlyScope patch (see BG3Tools scripts/lslib_fork_linux_build/)"
else
    echo "Patch déjà appliqué sur ce clone, on passe directement au build."
fi

# Second patch (19c / patch NMCM AbsoluteDefeat) : Divine.CLI.CommandLineActions.TryToValidatePath
# plante avec "System.InvalidOperationException: This operation is not supported for a relative
# URI." sur TOUT chemin absolu Unix passé à -s/-d ("/…"), y compris hors de ce dépôt — reproduit sur
# un dossier /tmp minimal. Cause : Uri.TryCreate(path, UriKind.RelativeOrAbsolute) ne reconnaît un
# chemin comme IsFile que pour une syntaxe Windows (lettre de lecteur/UNC) ou un "file://" explicite ;
# un chemin absolu Unix est parsé comme URI RELATIVE, et uri.IsFile lève alors l'exception. Le patch
# remplace ce détour par Uri par le seul test Path.IsPathRooted(path), déjà ce que Path.GetFullPath
# utilise juste après — comportement identique sous Windows, corrigé sous Linux. Même politique que
# le patch 0001 : appliqué ici uniquement, jamais poussé sur le remote sans accord explicite.
PATCH_FILE_2="$SCRIPT_DIR/0002-fix-linux-path-validation.patch"
if ! command git log --oneline | grep -q "BG3Tools Linux patch.*TryToValidatePath\|fix-linux-path-validation"; then
    if command git apply --check "$PATCH_FILE_2" 2>/dev/null; then
        echo "Application du patch de correction de validation de chemin (Linux) ..."
        command git apply "$PATCH_FILE_2"
        command git add -A
        command git commit -m "Fix Linux path validation in TryToValidatePath (see BG3Tools scripts/lslib_fork_linux_build/0002-fix-linux-path-validation.patch)"
    else
        echo "Patch 0002 déjà appliqué (ou incompatible avec l'état actuel du clone), on continue."
    fi
else
    echo "Patch 0002 déjà appliqué sur ce clone, on passe directement au build."
fi

echo "=== dotnet build Divine/Divine.csproj -c Release ==="
if command -v dotnet >/dev/null 2>&1; then
    dotnet build Divine/Divine.csproj -c Release
elif command -v distrobox >/dev/null 2>&1 && distrobox list 2>/dev/null | grep -q 'bg3tools-dotnet'; then
    echo "(dotnet absent en natif — utilisation du conteneur distrobox bg3tools-dotnet)"
    distrobox enter bg3tools-dotnet -- bash -lc "cd '$CLONE_DIR' && dotnet build Divine/Divine.csproj -c Release"
else
    echo "Ni 'dotnet' (SDK .NET 8+) ni un conteneur distrobox 'bg3tools-dotnet' trouvés." >&2
    echo "Installer le SDK .NET 8, ou créer un conteneur distrobox adapté, puis relancer." >&2
    exit 1
fi

echo
echo "Build terminé. Binaire : $CLONE_DIR/Divine/bin/Release/net8.0/Divine.dll"
echo "(clone conservé dans $CLONE_DIR pour inspection/relecture du diff appliqué)"

if [ "$CLEANUP_ON_EXIT" -eq 1 ]; then
    echo "Rappel : ce dossier est temporaire (mktemp) et ne survivra pas au redémarrage."
fi
