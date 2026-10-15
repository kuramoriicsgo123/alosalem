@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title ASA Shop - Installation
cd /d "%~dp0"
if errorlevel 1 goto dossier_erreur

echo.
echo Installation du bot de boutique ARK ASA
echo Le token Discord ne vous sera jamais demandé dans cette fenêtre.
echo.

if not exist "requirements.txt" goto dossier_incomplet
if not exist "requirements.lock" goto dossier_incomplet
if not exist "main.py" goto dossier_incomplet
if not exist "config.example.json" goto dossier_incomplet
if not exist ".env.example" goto dossier_incomplet
if not exist "products.json" goto dossier_incomplet
if not exist "prices.json" goto dossier_incomplet
if not exist "structure.json" goto dossier_incomplet
if exist ".venv\Scripts\python.exe" goto verifier_python

py -3.12 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "ASA_PYTHON_CMD=py -3.12"
    goto creer_environnement
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "ASA_PYTHON_CMD=py -3"
    goto creer_environnement
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "ASA_PYTHON_CMD=python"
    goto creer_environnement
)
echo ERREUR : Python 3.11 ou plus récent est introuvable.
echo Installez de préférence Python 3.12 depuis https://www.python.org/downloads/windows/
echo Cochez « Add python.exe to PATH », puis relancez ce fichier.
goto echec

:creer_environnement
echo Création de l'environnement Python local .venv...
%ASA_PYTHON_CMD% -m venv ".venv"
if errorlevel 1 (
    echo ERREUR : impossible de créer l'environnement Python.
    echo Extrayez le ZIP dans un dossier où vous pouvez écrire.
    goto echec
)

:verifier_python
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo ERREUR : l'environnement .venv existant est inutilisable ou trop ancien.
    echo Renommez uniquement le dossier .venv en .venv-ancien, puis relancez.
    echo Conservez votre configuration, votre .env et vos données.
    goto echec
)
echo Installation des dépendances indiquées dans requirements.txt...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --requirement "requirements.txt"
if errorlevel 1 (
    echo ERREUR : installation des dépendances impossible.
    echo Vérifiez votre connexion et le message ci-dessus. Ne désactivez pas TLS.
    goto echec
)

if not exist "config.json" (
    copy /y "config.example.json" "config.json" >nul
    if errorlevel 1 goto copie_erreur
)
if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    if errorlevel 1 goto copie_erreur
)
echo Vérification locale des fichiers, sans connexion à Discord...
".venv\Scripts\python.exe" "main.py" --check
if errorlevel 1 (
    echo ERREUR : corrigez les fichiers signalés ci-dessus, puis relancez.
    goto echec
)
echo.
echo Installation terminée.
echo 1. Suivez README_FR.md pour créer le bot et l'inviter sur votre serveur.
echo 2. Renseignez config.json et votre token privé dans .env.
echo 3. Lancez DEMARRER_WINDOWS.bat.
echo Les fichiers existants de configuration et .env ont été conservés.
echo.
pause
exit /b 0

:dossier_erreur
echo ERREUR : impossible d'ouvrir le dossier du programme.
goto echec
:dossier_incomplet
echo ERREUR : dossier incomplet. Extrayez tout le ZIP avant l'installation.
goto echec
:copie_erreur
echo ERREUR : impossible de créer config.json ou .env.
echo Vérifiez la présence des fichiers exemples et les droits du dossier.
:echec
echo Consultez README_FR.md pour le dépannage.
pause
exit /b 1
