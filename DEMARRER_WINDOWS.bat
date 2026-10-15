@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title ASA Shop - Bot Discord
cd /d "%~dp0"
if errorlevel 1 (
    echo ERREUR : impossible d'ouvrir le dossier du programme.
    goto echec
)
if not exist ".venv\Scripts\python.exe" (
    echo ERREUR : lancez d'abord INSTALLER_WINDOWS.bat.
    goto echec
)
if not exist "config.json" (
    echo ERREUR : config.json est absent. Relancez INSTALLER_WINDOWS.bat.
    goto echec
)
if not exist "main.py" (
    echo ERREUR : dossier incomplet. Extrayez tout le ZIP.
    goto echec
)
echo Vérification de la configuration...
".venv\Scripts\python.exe" "main.py" --check
if errorlevel 1 goto echec
echo.
echo Connexion à Discord et synchronisation de la boutique...
echo Gardez cette fenêtre ouverte pour que les boutons et tickets fonctionnent.
echo Arrêt : Ctrl+C. Ne lancez pas une deuxième copie du bot.
echo.
".venv\Scripts\python.exe" "main.py" --setup
set "ASA_EXIT_CODE=%ERRORLEVEL%"
if not "%ASA_EXIT_CODE%"=="0" (
    echo.
    echo Le bot s'est arrêté avec une erreur. Consultez le message ci-dessus.
    echo Vérifiez le token dans .env, guild_id dans config.json et les permissions.
    echo Aide détaillée dans README_FR.md.
    pause
    exit /b %ASA_EXIT_CODE%
)
exit /b 0

:echec
echo Corrigez l'erreur signalée, puis relancez DEMARRER_WINDOWS.bat.
echo Aide détaillée dans README_FR.md.
pause
exit /b 1
