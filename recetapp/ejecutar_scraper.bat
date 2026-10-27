@echo off
:: Ir al directorio exacto del proyecto
cd /d "D:\Proyectos\Comparador de precios\BUSQUEDA-EAN-main\recetapp"

:: Si utilizas un entorno virtual llamado .venv o venv, descomenta la siguiente linea:
:: call "D:\Proyectos\Comparador de precios\BUSQUEDA-EAN-main\recetapp\.venv\Scripts\activate.bat"

:: Ejecutar el scraper maestro y registrar la salida completa
python scraper.py >> "data\scraper_noche.log" 2>&1