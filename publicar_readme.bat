@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Publicando iG2P "so codigo" (dados ficam locais, fora do Git)
echo ============================================================
echo.
echo [1/3] Re-indexando o repositorio conforme o .gitignore...
git rm -r --cached . >nul 2>&1
git add .
echo.
echo [2/3] Commit...
git commit -m "docs: README bilingue + prints + secrets.example; remove dados municipais do versionamento"
echo.
echo [3/3] Enviando para o GitHub (push)...
git push
echo.
echo ============================================================
echo  Concluido. Confira no GitHub se os dados (CSVs) sairam e
echo  se o README apareceu. Pode fechar esta janela.
echo ============================================================
pause
