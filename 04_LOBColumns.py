from __future__ import annotations

import logging
import os
import argparse
import json
from typing import Any, Optional
from dotenv import load_dotenv
from utils.etl_helpers import SQLExecutionError
from tqdm import tqdm
import tkinter as tk
from tkinter import messagebox

import sqlalchemy
from db.connections import get_target_connection
from utils.logging_helper import setup_logging, operation_counts
from config.settings import settings, parse_database_name
from config import ETLConstants

from utils.etl_helpers import (
    log_exception_to_file,
    load_sql,
    run_sql_script_no_tracking,  
    transaction_scope,
    execute_sql_with_timeout,
)
from etl.core import sanitize_sql

logger = logging.getLogger(__name__)

DEFAULT_LOG_FILE = "PreDMSErrorLog_LOBS.txt"

# Database name used within the dynamic SQL statements
conn_val = settings.mssql_target_conn_str if settings.mssql_target_conn_str else None
DB_NAME = settings.mssql_target_db_name or parse_database_name(conn_val)

def parse_args() -> argparse.Namespace:
    """Parse command line arguments for the LOB Column processing script.

    Refer to ``README.md`` for an overview of expected options and defaults.
    """
    parser = argparse.ArgumentParser(description="LOB Column Processing")
    parser.add_argument(
        "--log-file",
        help="Path to the error log file. Overrides the EJ_LOG_DIR environment variable."
    )
    parser.add_argument(
        "--include-empty", 
        action="store_true",
        help="Include empty tables in the LOB column processing."
    )
    parser.add_argument(
        "--config-file",
        default="config/secure_config.json",
        help="Path to JSON configuration file with all settings."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Number of rows to fetch per batch when processing LOB columns."
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging."
    )
    return parser.parse_args()
def validate_environment() -> None:
    """Validate required environment variables and their values."""
    required_vars = {
        'MSSQL_TARGET_CONN_STR': "Database connection string is required",
    }
    
    optional_vars = {
        'EJ_LOG_DIR': "Directory for log files (defaults to current directory)",
        'INCLUDE_EMPTY_TABLES': "Set to '1' to include empty tables (defaults to '0')",
        'SQL_TIMEOUT': "Timeout in seconds for SQL operations (defaults to 300)"
    }
    
    # Check required vars
    missing = []
    for var, desc in required_vars.items():
        if not os.environ.get(var):
            missing.append(f"{var}: {desc}")
    
    if missing:
        raise EnvironmentError(f"Missing required environment variables:\n" + 
                              "\n".join(missing))
    
    # Log optional vars
    for var, desc in optional_vars.items():
        value = os.environ.get(var)
        if value:
            logger.info(f"Using {var}={value}")
        else:
            logger.info(f"{var} not set. {desc}")
def load_config(config_file: str | None = None) -> dict[str, Any]:
    """Load configuration from JSON file if provided, otherwise use defaults."""
    config: dict[str, Any] = {
        "include_empty_tables": False,
        "always_include_tables": [],
        "log_filename": DEFAULT_LOG_FILE,
        "sql_timeout": ETLConstants.DEFAULT_SQL_TIMEOUT,  # seconds
        "batch_size": ETLConstants.DEFAULT_BULK_INSERT_BATCH_SIZE,
    }
    
    if config_file and os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
            logger.info(f"Loaded configuration from {config_file}")
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
    
    return config
def get_max_length(conn: Any, schema: str, table: str, column: str, datatype: str, timeout: int) -> Optional[int]:
    """Determine the maximum length needed for a text/varchar column."""
    try:
        # Validate identifiers to prevent SQL injection
        from etl.core import validate_sql_identifier
        
        schema = validate_sql_identifier(schema)
        table = validate_sql_identifier(table)
        column = validate_sql_identifier(column)
        
        if datatype.lower() in ("varchar", "nvarchar"):
            sql = f"SELECT MAX(LEN([{column}])) FROM [{schema}].[{table}]"
        elif datatype.lower() in ("text", "ntext"):
            sql = f"SELECT MAX(LEN(CAST([{column}] AS NVARCHAR(MAX)))) FROM [{schema}].[{table}]"
        else:
            return None

        cur = execute_sql_with_timeout(conn, sql, timeout=timeout)
        result = cur.fetchone()
        return result[0] if result and result[0] is not None else 0
    except Exception as e:
        logger.error(f"Error getting max length for {schema}.{table}.{column}: {e}")
        return None
def build_alter_column_sql(
    schema: str,
    table: str,
    column: str,
    datatype: str,
    max_length: Optional[int],
) -> str:
    """Build the SQL statement to alter a column based on its max length."""
    if max_length is None or max_length == 0:
        return f"ALTER TABLE [{schema}].[{table}] ALTER COLUMN [{column}] CHAR(1) NULL"
    elif max_length > 8000:
        return f"ALTER TABLE [{schema}].[{table}] ALTER COLUMN [{column}] TEXT NULL"
    else:
        return f"ALTER TABLE [{schema}].[{table}] ALTER COLUMN [{column}] VARCHAR({max_length}) NULL"
def create_lob_tracking_table(conn: Any, config: dict[str, Any]) -> None:
    """Create the table to track LOB column updates."""
    logger.info("Creating LOB_COLUMN_UPDATES tracking table")
    gather_lobs_sql = load_sql('lob/gather_lobs.sql', DB_NAME)
    
    # Use run_sql_script_no_tracking to ensure this always executes
    run_sql_script_no_tracking(conn, 'gather_lobs', gather_lobs_sql, timeout=config['sql_timeout'])
    
    logger.info("LOB tracking table created successfully")
def gather_lob_columns(
    conn: Any,
    config: dict[str, Any],
    log_file: str,
) -> None:
    """Gather information about LOB columns and determine optimal sizes."""
    logger.info("Gathering information about LOB columns")

    with transaction_scope(conn):
        # Query for LOB columns
        query = f"""
        SELECT
            s.[NAME] AS SchemaName,
            t.[NAME] AS TableName,
            c.[NAME] AS ColumnName,
            TYPE_NAME(c.user_type_id) AS DataType,
            CASE WHEN TYPE_NAME(c.user_type_id) IN ('varchar', 'nvarchar')
                 THEN c.max_length ELSE NULL END AS CurrentLength,
            CASE WHEN EXISTS (SELECT 1 FROM sys.partitions p WHERE p.object_id = t.object_id AND p.index_id IN (0,1))
                THEN (SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id = t.object_id AND p.index_id IN (0,1))
                ELSE 0 END AS RowCnt
        FROM {DB_NAME}.sys.tables t
        INNER JOIN {DB_NAME}.sys.schemas s ON t.schema_id=s.schema_id
        INNER JOIN {DB_NAME}.sys.columns c ON t.object_id=c.object_id
        WHERE t.[NAME] NOT IN (
            'TablesToConvert','TablesToConvert_Financial','TablesToConvert_Operations'
        )
        AND (
            TYPE_NAME(c.user_type_id) IN ('text', 'ntext')
            OR (TYPE_NAME(c.user_type_id) IN ('varchar', 'nvarchar')
                AND (c.max_length > 5000 OR c.max_length=-1))
        )
        ORDER BY s.[NAME], t.[NAME], c.[NAME]
        """

        cursor = execute_sql_with_timeout(
            conn, query, timeout=config["sql_timeout"]
        )

        # Handle cursor results - force everything to be dictionaries
        try:
            if hasattr(cursor, "mappings"):
                # SQLAlchemy 1.4+ CursorResult object
                rows = list(cursor.mappings())
                logger.info(f"Using SQLAlchemy mappings, got {len(rows)} rows")
            elif hasattr(cursor, "keys") and callable(cursor.keys):
                # Older SQLAlchemy versions
                columns = cursor.keys()
                rows_data = cursor.fetchall()
                rows = [dict(zip(columns, row)) for row in rows_data]
                logger.info(f"Using SQLAlchemy keys/fetchall, got {len(rows)} rows")
            elif hasattr(cursor, "description"):
                # Standard DB-API cursor (pyodbc)
                columns = [desc[0] for desc in cursor.description]
                rows_data = cursor.fetchall()
                rows = [dict(zip(columns, row)) for row in rows_data]
                logger.info(f"Using DB-API description, got {len(rows)} rows")
            else:
                # Last resort fallback
                logger.error("Unknown cursor type, cannot process")
                return
        except Exception as e:
            logger.error(f"Error processing cursor results: {e}")
            return

        # Verify we have data
        if not rows:
            logger.info("No LOB columns found to process")
            return

        batch_size = config.get(
            "batch_size", ETLConstants.DEFAULT_BULK_INSERT_BATCH_SIZE
        )

        processed = 0
        progress = tqdm(total=len(rows), desc="Analyzing LOB Columns", unit="column")
        
        # Prepare insert query using SQLAlchemy style
        insert_sql = f"""
            INSERT INTO {DB_NAME}.dbo.LOB_COLUMN_UPDATES
            (SchemaName, TableName, ColumnName, DataType, CurrentLength, RowCnt, MaxLen, AlterStatement)
            VALUES (:schema_name, :table_name, :column_name, :datatype, :current_length, :row_cnt, :max_len, :alter_statement)
        """
        
        for row in rows:
            # Enhanced: Handle all SQLAlchemy row types
            try:
                if hasattr(row, 'get') and callable(row.get):
                    # Both dict and RowMapping have .get() method
                    row_dict = row
                elif hasattr(row, '_mapping'):
                    # Some SQLAlchemy objects have _mapping attribute
                    row_dict = dict(row._mapping)
                elif hasattr(row, '__getitem__') and hasattr(row, 'keys'):
                    # Row-like object that can be converted to dict
                    row_dict = dict(row)
                else:
                    # Last resort: try to convert to dict
                    row_dict = dict(row)
            except Exception as convert_error:
                logger.error(f"Cannot convert row to dictionary: {type(row)}: {row} - Error: {convert_error}")
                continue
                
            schema_name = row_dict.get("SchemaName")
            table_name = row_dict.get("TableName")
            column_name = row_dict.get("ColumnName")
            datatype = row_dict.get("DataType")
            row_cnt = row_dict.get("RowCnt") or 0
            
            # Validate required fields
            if not all([schema_name, table_name, column_name, datatype]):
                logger.error(f"Missing required fields in row: {row_dict}")
                continue
            
            # Skip empty tables unless configured otherwise
            overrides = {t.lower() for t in config.get("always_include_tables", [])}
            full_name = f"{schema_name}.{table_name}".lower()
            if (
                not config["include_empty_tables"]
                and row_cnt <= 0
                and full_name not in overrides
            ):
                logger.info(f"Skipping {schema_name}.{table_name}.{column_name}: row count is {row_cnt}")
                continue

            try:
                max_length = get_max_length(
                    conn,
                    schema_name,
                    table_name,
                    column_name,
                    datatype,
                    config["sql_timeout"],
                )
                alter_column_sql = build_alter_column_sql(
                    schema_name,
                    table_name,
                    column_name,
                    datatype,
                    max_length,
                )

                # Use SQLAlchemy-style parameterized query execution
                try:
                    conn.execute(
                        sqlalchemy.text(insert_sql),
                        {
                            'schema_name': schema_name,
                            'table_name': table_name,
                            'column_name': column_name,
                            'datatype': datatype,
                            'current_length': row_dict.get("CurrentLength"),
                            'row_cnt': row_cnt,
                            'max_len': max_length,
                            'alter_statement': alter_column_sql,
                        }
                    )
                except Exception as e:
                    conn.rollback()
                    error_msg = (
                        f"Error inserting LOB column {schema_name}.{table_name}.{column_name}: {e}"
                    )
                    logger.error(error_msg)
                    log_exception_to_file(error_msg, log_file)
                    
            except Exception as e:
                conn.rollback()
                error_msg = (
                    f"Error processing LOB column {schema_name}.{table_name}.{column_name}: {e}"
                )
                logger.error(error_msg)
                log_exception_to_file(error_msg, log_file)
                
            processed += 1
            progress.update(1)

            if processed % batch_size == 0:
                conn.commit()

        progress.close()
        if processed % batch_size != 0:
            conn.commit()
        logger.info(f"Analyzed and cataloged {processed} LOB columns")
def execute_lob_column_updates(
    conn: Any,
    config: dict[str, Any],
    log_file: str,
) -> None:
    """Execute the ALTER statements to optimize LOB columns."""
    logger.info("Executing ALTER TABLE statements for LOB columns")

    with transaction_scope(conn):
        query = f"""
        SELECT REPLACE(S.ALTERSTATEMENT,' NULL',';') AS Alter_Statement
        FROM {DB_NAME}.dbo.LOB_COLUMN_UPDATES S
        WHERE S.TABLENAME NOT LIKE '%LOB_COL%'
        ORDER BY S.MAXLEN DESC
        """

        cursor = execute_sql_with_timeout(
            conn, query, timeout=config["sql_timeout"]
        )
        
        # Standardized cursor handling
        columns = None
        try:
            if hasattr(cursor, "mappings"):
                # SQLAlchemy 1.4+ CursorResult object - returns dictionaries directly
                rows = list(cursor.mappings())
                logger.debug(f"Using SQLAlchemy mappings, got {len(rows)} rows")
            elif hasattr(cursor, "keys") and callable(cursor.keys):
                # Older SQLAlchemy versions
                columns = cursor.keys()
                rows_data = cursor.fetchall()
                rows = [dict(zip(columns, row)) for row in rows_data]
                logger.debug(f"Using SQLAlchemy keys/fetchall, got {len(rows)} rows")
            elif hasattr(cursor, "description"):
                # Standard DB-API cursor (pyodbc)
                columns = [desc[0] for desc in cursor.description]
                rows_data = cursor.fetchall()
                rows = [dict(zip(columns, row)) for row in rows_data]
                logger.debug(f"Using DB-API description, got {len(rows)} rows")
            else:
                # Last resort fallback
                rows = list(cursor)
        except Exception as e:
            logger.error(f"Error processing cursor results: {e}")
            return

        for idx, row in enumerate(tqdm(rows, desc="Optimizing LOB Columns", unit="column"), 1):
            # Since we standardized all cursor results to dictionaries above, 
            # we should always get dictionaries here
            if isinstance(row, dict):
                row_dict = row
            elif hasattr(row, '_mapping'):
                # For SQLAlchemy RowMapping objects
                row_dict = row._mapping
            else:
                # This should not happen with our standardized approach above
                logger.error(f"Unexpected row type {type(row)}: {row}")
                continue
                
            alter_sql = row_dict.get('Alter_Statement')

            if alter_sql:
                try:
                    sanitize_sql(
                        conn,
                        alter_sql,
                        timeout=config['sql_timeout'],
                    )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    error_msg = f"Failed to alter column (statement {idx}): {e}"
                    logger.error(error_msg)
                    log_exception_to_file(error_msg, log_file)
                    raise

    logger.info(f"Completed optimizing {len(rows)} LOB columns")
def show_completion_message() -> bool:
    """Show a message box indicating completion."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    proceed = messagebox.askyesno(
        "LOB Column Processing Complete",
        "LOB column optimization is complete.\n\n"
        "The database is now ready for transfer to AWS DMS.\n\n"
        "Click Yes to exit."
    )
    root.destroy()
    return proceed

def main() -> None:
    try:
        # Initialize configuration
        args = parse_args()
        setup_logging()
        load_dotenv()
        validate_environment()
        
        # Set up logging level
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        from db.health import check_target_connection
        if not check_target_connection():
            logger.error("Database connectivity check failed")
            return
        
        # Load and merge configuration
        config = load_config(args.config_file)

        # Override config with environment variables
        if os.environ.get("INCLUDE_EMPTY_TABLES") == "1":
            config["include_empty_tables"] = True
        if os.environ.get("SQL_TIMEOUT"):
            config["sql_timeout"] = int(os.environ.get("SQL_TIMEOUT"))
        if os.environ.get("BATCH_SIZE"):
            config["batch_size"] = int(os.environ.get("BATCH_SIZE"))

        # Override config with command line arguments
        if args.include_empty:
            config["include_empty_tables"] = True
        if args.batch_size:
            config["batch_size"] = args.batch_size

        # Set up log file path
        config['log_file'] = args.log_file or os.path.join(
            os.environ.get("EJ_LOG_DIR", ""), 
            config["log_filename"]
        )
        
        logger.info(f"Using configuration: {json.dumps(config, indent=2)}")
        
        # Begin database operations
        try:
            with get_target_connection() as conn:
                # Step 1: Create tracking table for LOB columns
                create_lob_tracking_table(conn, config)
                
                # Step 2: Gather LOB column information
                gather_lob_columns(conn, config, config['log_file'])
                
                # Step 3: Execute column alterations
                execute_lob_column_updates(conn, config, config['log_file'])
                
                # Step 4: Show completion message
                show_completion_message()
                logger.info(
                    "Run completed - successes: %s failures: %s",
                    operation_counts["success"],
                    operation_counts["failure"],
                )
                
        except Exception as e:
            logger.exception("Unexpected error during database operations")
            raise
                
    except Exception as e:
        logger.exception("Unexpected error")
        import traceback
        error_details = traceback.format_exc()
        
        # Try to log the error to file
        try:
            log_file = config.get('log_file', DEFAULT_LOG_FILE)
            log_exception_to_file(error_details, log_file)
        except Exception as log_exc:
            logger.error(f"Failed to write to error log: {log_exc}")
        
        # Try to show error message box
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("ETL Script Error", f"An error occurred:\n\n{error_details}")
            root.destroy()
        except Exception as msgbox_exc:
            logger.error(f"Failed to show error message box: {msgbox_exc}")
if __name__ == "__main__":
    main()