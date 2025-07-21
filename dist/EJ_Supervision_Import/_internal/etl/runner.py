import os
import sys
import logging
import subprocess
import threading
import queue
import re
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPTS = [
    ("Justice DB Import", "01_JusticeDB_Import.py"),
    ("Operations DB Import", "02_OperationsDB_Import.py"),
    ("Financial DB Import", "03_FinancialDB_Import.py"),
    ("LOB Column Processing", "04_LOBColumns.py"),
]


def run_sequential_etl(env: dict) -> None:
    """Run the ETL modules sequentially in-process."""
    from importlib import import_module

    import_modules = [
        "01_JusticeDB_Import",
        "02_OperationsDB_Import",
        "03_FinancialDB_Import",
        "04_LOBColumns",
    ]

    old_environ = os.environ.copy()
    os.environ.update(env)

    try:
        for module_name in import_modules:
            module = import_module(module_name)
            proceed = module.main()
            if not proceed:
                logger.info("Stopped after %s", module_name)
                break
    finally:
        os.environ.clear()
        os.environ.update(old_environ)


def _is_frozen():
    """Check if running as a frozen executable (PyInstaller, cx_Freeze, etc.)"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


class ScriptRunner(threading.Thread):
    """Run an ETL script in a background thread."""

    def __init__(self, script_path: str, env: dict,
                 output_queue: "queue.Queue[str]",
                 status_queue: "queue.Queue[tuple[str, str]]") -> None:
        super().__init__(daemon=True)
        self.script_path = script_path
        self.env = env
        self.output_queue = output_queue
        self.status_queue = status_queue
        self.process: subprocess.Popen[str] | None = None
        self._stop_event = threading.Event()

    def run(self) -> None:
        debug_log_path = f"{self.script_path}_debug.log"
        
        # If running as frozen executable, run in-process to avoid launching new GUI instances
        if _is_frozen():
            self._run_in_process(debug_log_path)
        else:
            self._run_subprocess(debug_log_path)

    def _run_in_process(self, debug_log_path: str) -> None:
        """Run the script in-process (for frozen executables)"""
        try:
            self.status_queue.put((self.script_path, "Starting..."))
            self.output_queue.put(("output", f"[{datetime.now().strftime('%H:%M:%S')}] Starting {self.script_path} (in-process)...\n"))
            
            # Set up environment
            old_environ = os.environ.copy()
            os.environ.update(self.env)
            
            # Extract module name from script path
            script_name = Path(self.script_path).stem
            
            try:
                # Import and run the module
                module = import_module(script_name)
                
                # Capture output by temporarily redirecting stdout/stderr
                import io
                from contextlib import redirect_stdout, redirect_stderr
                
                output_buffer = io.StringIO()
                error_buffer = io.StringIO()
                
                with redirect_stdout(output_buffer), redirect_stderr(error_buffer):
                    result = module.main()
                
                # Get captured output
                stdout_content = output_buffer.getvalue()
                stderr_content = error_buffer.getvalue()
                
                # Send output to UI
                if stdout_content:
                    for line in stdout_content.split('\n'):
                        if line.strip():
                            self.output_queue.put(("output", line + '\n'))
                            self._parse_status(line)
                
                if stderr_content:
                    for line in stderr_content.split('\n'):
                        if line.strip():
                            self.output_queue.put(("output", f"ERROR: {line}\n"))
                
                # Write debug log
                with open(debug_log_path, "w", encoding="utf-8") as debug_log:
                    debug_log.write(f"=== In-process execution of {self.script_path} ===\n")
                    debug_log.write("STDOUT:\n")
                    debug_log.write(stdout_content)
                    debug_log.write("\nSTDERR:\n")
                    debug_log.write(stderr_content)
                    debug_log.write(f"\nResult: {result}\n")
                
                if result:
                    self.status_queue.put((self.script_path, "COMPLETED"))
                    self.output_queue.put(("output", f"\nFinished {self.script_path} successfully\n"))
                else:
                    self.status_queue.put((self.script_path, "FAILED"))
                    self.output_queue.put(("output", f"\n{self.script_path} returned False\n"))
                
            except Exception as e:
                error_msg = f"Error running {self.script_path} in-process: {e}\n"
                self.output_queue.put(("output", error_msg))
                self.status_queue.put((self.script_path, "EXECUTION ERROR"))
                logger.error(error_msg)
                
                # Write error to debug log
                with open(debug_log_path, "w", encoding="utf-8") as debug_log:
                    debug_log.write(f"=== Error in in-process execution of {self.script_path} ===\n")
                    debug_log.write(f"Error: {e}\n")
                    debug_log.write(f"Exception type: {type(e).__name__}\n")
            
            finally:
                # Restore environment
                os.environ.clear()
                os.environ.update(old_environ)
                
        except Exception as e:
            error_msg = f"Fatal error in in-process execution: {e}\n"
            self.output_queue.put(("output", error_msg))
            self.status_queue.put((self.script_path, "FATAL ERROR"))
            logger.error(error_msg)
        
        finally:
            self.output_queue.put(("done", None))

    def _run_subprocess(self, debug_log_path: str) -> None:
        """Run the script as a subprocess (for development environment)"""
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-u", self.script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.env,
            )
            self.status_queue.put((self.script_path, "Starting..."))
            with open(debug_log_path, "w", encoding="utf-8") as debug_log:
                line_count = 0
                last_ui_update = time.time()
                while not self._stop_event.is_set():
                    line = self.process.stdout.readline() if self.process.stdout else ""
                    if not line:
                        if self.process.poll() is not None:
                            break
                        continue
                    debug_log.write(line)
                    debug_log.flush()
                    line_count += 1
                    self._parse_status(line)
                    current_time = time.time()
                    if (
                        current_time - last_ui_update > 0.1
                        or "Drop If Exists" in line
                        or "Select INTO" in line
                        or "Error" in line
                        or "ERROR" in line
                        or line_count <= 10
                    ):
                        self.output_queue.put(("output", line))
                        last_ui_update = current_time
                    if line_count % 100 == 0:
                        summary = f"[{datetime.now().strftime('%H:%M:%S')}] Processed {line_count} lines...\n"
                        self.output_queue.put(("output", summary))
            return_code = self.process.wait()
            if return_code != 0:
                self.output_queue.put(("output", f"\nProcess exited with return code {return_code}\n"))
                self.status_queue.put((self.script_path, f"FAILED (code {return_code})"))
            else:
                self.status_queue.put((self.script_path, "COMPLETED"))
            self.output_queue.put(("output", f"\nFinished {self.script_path}\nDebug log: {debug_log_path}\n"))
        except Exception as e:  # pragma: no cover - just in case
            error_msg = f"Error running {self.script_path}: {e}\n"
            self.output_queue.put(("output", error_msg))
            self.status_queue.put((self.script_path, "EXECUTION ERROR"))
            logger.error(error_msg)
        finally:
            self.output_queue.put(("done", None))

    def _parse_status(self, line: str) -> None:
        try:
            if "Drop If Exists" in line:
                match = re.search(r"RowID:(\d+) Drop If Exists:\((.*?)\)", line)
                if match:
                    _, table_info = match.groups()
                    self.status_queue.put((self.script_path, f"Dropping: {table_info}"))
            elif "Select INTO" in line:
                match = re.search(r"RowID:(\d+) Select INTO:\((.*?)\)", line)
                if match:
                    _, table_info = match.groups()
                    self.status_queue.put((self.script_path, f"Creating: {table_info}"))
            elif "PK Creation" in line:
                match = re.search(r"PK Creation:\((.*?)\)", line)
                if match:
                    table_info = match.group(1)
                    self.status_queue.put((self.script_path, f"Creating PK: {table_info}"))
            elif "Gathering" in line:
                self.status_queue.put((self.script_path, line.strip()))
            elif "completed successfully" in line:
                self.status_queue.put((self.script_path, "Processing..."))
        except Exception:
            pass

    def stop(self) -> None:
        self._stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait()


def run_script(script_path: str, env: dict,
               output_queue: "queue.Queue[str]",
               status_queue: "queue.Queue[tuple[str, str]]") -> ScriptRunner:
    """Convenience wrapper to start a ``ScriptRunner``."""
    runner = ScriptRunner(script_path, env, output_queue, status_queue)
    runner.start()
    return runner
