@echo off
echo ============================================
echo  SAP QM Comparator - PyInstaller Build
echo ============================================

echo [1/3] Installing PyInstaller...
pip install pyinstaller --quiet

echo [2/3] Building EXE...
pyinstaller sap_qm_comparator.spec --clean --noconfirm

echo [3/3] Done!
echo.
echo Output folder: dist\SAP_QM_Comparator\
echo Share the entire "SAP_QM_Comparator" folder with colleagues.
echo They double-click SAP_QM_Comparator.exe to launch.
echo.
pause
