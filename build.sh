#!/usr/bin/env bash
# Salir si hay algún error
set -o errexit

# 1. Actualizar pip
python -m pip install --upgrade pip

# 2. Instalar dependencias de Python
pip install -r requirements.txt

# 3. Instalar Chromium y las dependencias de sistema (Ubuntu) que exige Playwright
playwright install chromium
playwright install-deps chromium