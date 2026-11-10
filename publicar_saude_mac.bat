@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Publicando: recorte Secretaria x Hospital na categoria MAC
echo  (so Cassia, para validacao). Dados locais ficam fora do Git.
echo ============================================================
echo.
git rm -r --cached . >nul 2>&1
git add .
git commit -m "feat(saude): recorte Secretaria x Repasse ao Hospital na categoria MAC"
git push
echo.
echo ============================================================
echo  Se apareceu algo como "main -^> main" acima, deu certo.
echo  O app no Streamlit Cloud reimplanta sozinho em ~1-2 min.
echo ============================================================
pause
