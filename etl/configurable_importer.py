from __future__ import annotations

from typing import Any, Iterable, Tuple
import argparse
import logging
import os
import tkinter as tk
from tkinter import messagebox
from etl.base_importer import BaseDBImporter
from etl.core import safe_tqdm
from utils.etl_helpers import transaction_scope

logger = logging.getLogger(__name__)

class ConfigurableDBImporter(BaseDBImporter):
    """Generic importer configurable for each database type."""

    def __init__(
        self,
        db_type: str,
        preprocessing_steps: Iterable[Tuple[str, str]],
        gather_drop_select_script: str,
        update_joins_script: str,
        next_step: str,
    ) -> None:
        super().__init__()
        self.DB_TYPE = db_type
        self.DEFAULT_LOG_FILE = f"PreDMSErrorLog_{db_type}.txt"
        self.DEFAULT_CSV_FILE = f"EJ_{db_type}_Selects_ALL.csv"
        self.preprocessing_steps = list(preprocessing_steps)
        self.gather_drop_select_script = gather_drop_select_script
        self.update_joins_script = update_joins_script
        self.next_step = next_step

    def parse_args(self) -> os.PathLike:
        parser = argparse.ArgumentParser(
            description=f"{self.DB_TYPE} DB Import ETL Process"
        )
        parser.add_argument(
            "--log-file",
            help="Path to the error log file. Overrides the EJ_LOG_DIR environment variable.",
        )
        parser.add_argument(
            "--csv-file",
            help=f"Path to the {self.DB_TYPE} Selects CSV file. Overrides the EJ_CSV_DIR environment variable.",
        )
        parser.add_argument(
            "--include-empty",
            action="store_true",
            help="Include empty tables in the migration process.",
        )
        parser.add_argument(
            "--skip-pk-creation",
            action="store_true",
            help="Skip primary key and constraint creation step.",
        )
        parser.add_argument(
            "--csv-chunk-size",
            type=int,
            help="Number of rows per chunk when reading the CSV file.",
        )
        parser.add_argument(
            "--config-file",
            default="config/secure_config.json",
            help="Path to JSON configuration file with all settings.",
        )
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Enable verbose logging.",
        )
        parser.add_argument(
            "--extra-validation",
            action="store_true",
            help="Enable extra SQL validation checks",
        )
        return parser.parse_args()

    def execute_preprocessing(self, conn: Any) -> None:
        logger.info("Defining supervision scope...")
        with transaction_scope(conn):
            for name, script in safe_tqdm(self.preprocessing_steps, desc="SQL Script Progress", unit="step"):
                self.run_sql_file(conn, name, script)
        logger.info("All Staging steps completed successfully. Supervision Scope Defined.")

    def prepare_drop_and_select(self, conn: Any) -> None:
        logger.info("Gathering list of %s tables with SQL Commands to be migrated.", self.DB_TYPE)
        self.run_sql_file(conn, "gather_drops_and_selects", self.gather_drop_select_script)

    def _check_missing_tables_in_joins(self, conn: Any) -> None:
        """Check for tables that exist in TablesToConvert but not in TableUsedSelects."""
        try:
            # Define the path to the missing table check SQL file
            missing_table_check_script = f"{self.DB_TYPE.lower()}/missing_table_check.sql"
            
            # Execute the SQL file using the existing run_sql_file method
            self.run_sql_file(conn, "missing_table_check", missing_table_check_script)
            
            # The SQL script returns the count directly, so get the result
            cursor = conn.cursor()
            result = cursor.fetchone()
            missing_count = result[0] if result else 0
            
            if missing_count > 0:
                # Log the missing table count
                logger.warning(f"Found {missing_count} tables in TablesToConvert that are not in TableUsedSelects")
                
                # Show message box with Yes/No options
                try:
                    # Create a hidden root window for the message box
                    root = tk.Tk()
                    root.withdraw()
                    
                    message = (f"There are {missing_count} tables from your gather_drops_and_select_script "
                              f"that are not in your joins CSV file. Please investigate.\n\n"
                              f"Check the log file for detailed table names.\n\n"
                              f"Do you want to continue with the import process?")
                    
                    result = messagebox.askyesno(
                        f"{self.DB_TYPE} Import Warning",
                        message,
                        icon="warning"
                    )
                    
                    root.destroy()
                    
                    # If user clicks No, stop the program
                    if not result:
                        logger.info("User chose to stop the import process due to missing tables in joins CSV.")
                        import sys
                        sys.exit(1)
                    else:
                        logger.info("User chose to continue the import process despite missing tables in joins CSV.")
                        
                except Exception as gui_error:
                    # If GUI fails, just log the warning and continue
                    logger.warning(f"Could not display GUI warning: {gui_error}")
                    logger.warning(f"WARNING: {missing_count} tables from gather_drops_and_select_script are not in joins CSV file")
                    logger.info("Continuing with import process since GUI dialog failed.")
    
        except Exception as e:
            logger.error(f"Error checking for missing tables in joins: {e}")

    def update_joins_in_tables(self, conn: Any) -> None:
        logger.info("Updating JOINS in TablesToConvert List")
        
        # Check for missing tables before running the update
        self._check_missing_tables_in_joins(conn)
        
        self.run_sql_file(conn, "update_joins", self.update_joins_script)
        logger.info("Updating JOINS for %s tables is complete.", self.DB_TYPE)

    def get_next_step_name(self) -> str:
        return self.next_step
