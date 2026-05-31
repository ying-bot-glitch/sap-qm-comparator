@echo off
echo ============================================
echo  SAP QM Comparator - PyInstaller Build
echo ============================================

:: Try to find Python
set PYTHON=
for %%P in (python py python3) do (
    if not defined PYTHON (
        %%P --version >nul 2>&1 && set PYTHON=%%P
    )
)

if not defined PYTHON (
    echo [ERROR] Python not found in PATH.
    echo.
    echo Please open this build.bat using one of:
    echo   1. Anaconda Prompt  (search in Start Menu)
    echo   2. Run:  where python  to find Python path
    echo.
    pause
    exit /b 1
)

echo [OK] Using Python: %PYTHON%
%PYTHON% --version

echo.
echo [1/3] Installing dependencies...
%PYTHON% -m pip install pyinstaller streamlit pandas openpyxl oracledb python-dotenv pyyaml xlsxwriter jinja2 --quiet

echo [2/3] Building EXE...
%PYTHON% -m PyInstaller sap_qm_comparator.spec --clean --noconfirm

echo [3/3] Done!
echo.
echo Output folder: dist\SAP_QM_Comparator\
echo Zip the entire folder and share with colleagues.
echo.
pause
