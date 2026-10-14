#!/bin/sh
# Instala (na primeira vez) e abre o tolstack no navegador.
cd "$(dirname "$0")"
python3 -m pip install -e ".[gui]" && python3 -m streamlit run app/streamlit_app.py
