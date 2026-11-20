@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
pip install pyinstaller pywebview python-dotenv "psycopg[binary]" psycopg_pool
if not exist .env copy .env.example .env
echo.
echo Configure SUPABASE_DB_URL and account passwords in .env before launching.
echo Building Government AI Platform desktop folder...
pyinstaller --noconfirm --clean --onedir --windowed --name GovernmentAIPlatform ^
  --collect-all streamlit --collect-all streamlit_autorefresh --collect-all pandas ^
  --collect-all reportlab --collect-all PIL --collect-all webview --collect-all psycopg --collect-all psycopg_binary --collect-all psycopg_pool ^
  --hidden-import=webview.platforms.edgechromium --add-data "app.py;." ^
  --add-data "static;static" --add-data "holomotion;holomotion" ^
  --add-data "Downloads.zip;." --add-data ".streamlit;.streamlit" ^
  desktop_launcher.py
if errorlevel 1 exit /b 1
if not exist dist\GovernmentAIPlatform mkdir dist\GovernmentAIPlatform
copy .env dist\GovernmentAIPlatform\.env >nul
if exist dist\GovernmentAIPlatform\_internal\static xcopy /E /I /Y dist\GovernmentAIPlatform\_internal\static dist\GovernmentAIPlatform\static >nul
if exist dist\GovernmentAIPlatform\_internal\holomotion xcopy /E /I /Y dist\GovernmentAIPlatform\_internal\holomotion dist\GovernmentAIPlatform\holomotion >nul
if exist dist\GovernmentAIPlatform\_internal\.streamlit xcopy /E /I /Y dist\GovernmentAIPlatform\_internal\.streamlit dist\GovernmentAIPlatform\.streamlit >nul
if exist dist\GovernmentAIPlatform\_internal\Downloads.zip copy /Y dist\GovernmentAIPlatform\_internal\Downloads.zip dist\GovernmentAIPlatform\Downloads.zip >nul
echo.
echo Build completed. Output: dist\GovernmentAIPlatform\GovernmentAIPlatform.exe
echo Keep .env private. Do not email or publish it.
pause
