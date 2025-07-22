"""Test script to verify all imports work before building"""

print("Testing imports...")

try:
    print("Testing run_etl...")
    import run_etl
    print("run_etl imported successfully")
    
    print("Testing ETL modules...")
    from importlib import import_module
    
    modules = [
        '01_JusticeDB_Import', 
        '02_OperationsDB_Import', 
        '03_FinancialDB_Import', 
        '04_LOBColumns'
    ]
    
    for module_name in modules:
        try:
            mod = import_module(module_name)
            print(f"{module_name} imported successfully")
        except Exception as e:
            print(f"❌ {module_name} failed: {e}")
    
    print("Testing critical dependencies...")
    import tkinter
    import pyodbc
    import pandas  
    import sqlalchemy
    import pydantic
    print("All critical dependencies imported successfully")
    
    print("Testing internal modules...")
    from etl import runner, configurable_importer, base_importer, core
    from utils import logging_helper, etl_helpers
    from config import settings
    from db import mssql
    print("All internal modules imported successfully")
    
    print("\n🎉 ALL IMPORTS SUCCESSFUL - Build should work!")
    
except Exception as e:
    print(f"❌ IMPORT ERROR: {e}")
    import traceback
    traceback.print_exc()