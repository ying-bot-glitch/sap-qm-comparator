# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# Collect all Streamlit static assets (HTML/JS/CSS frontend)
st_datas = collect_data_files('streamlit', include_py_files=False)

# Copy package metadata (needed by streamlit's version detection)
meta_datas = copy_metadata('streamlit')
meta_datas += copy_metadata('pandas')
meta_datas += copy_metadata('altair')
meta_datas += copy_metadata('pyarrow')

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('app.py',          '.'),
        ('config',          'config'),
        ('src',             'src'),
        *st_datas,
        *meta_datas,
    ],
    hiddenimports=[
        # Streamlit internals
        'streamlit',
        'streamlit.web.cli',
        'streamlit.web.server',
        'streamlit.runtime',
        'streamlit.runtime.scriptrunner',
        'streamlit.runtime.state',
        'streamlit.components.v1',
        'streamlit.elements',
        # App dependencies
        'pandas',
        'openpyxl',
        'xlsxwriter',
        'oracledb',
        'yaml',
        'dotenv',
        'jinja2',
        'altair',
        'pyarrow',
        # src modules (explicit, in case auto-discovery misses them)
        'src',
        'src.orchestrator',
        'src.loaders.base',
        'src.loaders.file_loader',
        'src.loaders.oracle_loader',
        'src.comparators.base',
        'src.comparators.plko',
        'src.comparators.plpo',
        'src.comparators.plmk',
        'src.comparators.mapl',
        'src.reporters.excel_reporter',
        'src.reporters.html_reporter',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'PIL'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SAP_QM_Comparator',
    debug=False,
    strip=False,
    upx=True,
    console=True,   # keep console so users can see startup progress / errors
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='SAP_QM_Comparator',
)
