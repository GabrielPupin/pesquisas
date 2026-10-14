@echo off
REM Instala (na primeira vez) e abre o tolstack no navegador.
cd /d "%~dp0"
py -m pip install -e ".[gui]"
if errorlevel 1 (
  echo.
  echo ERRO: instale o Python 3.10+ em https://www.python.org/downloads/ marcando "Add Python to PATH".
  pause
  exit /b 1
)
py -m streamlit run app/streamlit_app.py
pause
