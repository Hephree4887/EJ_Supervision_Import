# ej_supervision_import.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['run_etl.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('sql_scripts', 'sql_scripts'),
        ('config', 'config'),
        ('utils', 'utils'),
        ('etl', 'etl'),
        ('db', 'db'),
    ],
    hiddenimports=[
        # GUI imports
        'tkinter',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
        'tkinter.filedialog',
        'tkinter.ttk',
        
        # Database and data processing
        'pyodbc',
        'pandas',
        'sqlalchemy',
        'sqlalchemy.dialects.mssql',
        'sqlalchemy.pool',
        
        # Configuration and security
        'pydantic',
        'pydantic_settings',
        'cryptography',
        'cryptography.fernet',
        'keyring',
        'keyring.backends',
        
        # Other utilities
        'dotenv',
        'tqdm',
        'importlib.util',
        'contextlib',
        'queue',
        'threading',
        'pathlib',
        'json',
        'logging',
        'logging.handlers',
        'datetime',
        'io',
        're',
        'os',
        'sys',
        
        # ETL modules that need to be imported dynamically
        '01_JusticeDB_Import',
        '02_OperationsDB_Import', 
        '03_FinancialDB_Import',
        '04_LOBColumns',
        
        # ETL dependencies
        'etl.configurable_importer',
        'etl.base_importer',
        'etl.core',
        'etl.runner',
        
        # Utils dependencies  
        'utils.logging_helper',
        'utils.etl_helpers',
        'utils.progress_tracker',
        
        # Config dependencies
        'config.settings',
        
        # DB dependencies
        'db.mssql',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'test',
        'tests',
        'unittest',
        'PIL',
        'scipy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EJ_Supervision_Import',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='EJ_Supervision_Import'
)
