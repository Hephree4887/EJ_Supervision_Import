import json
import logging
import os
import time
from typing import Any, Dict, Optional, Callable
from datetime import datetime
import threading

logger = logging.getLogger(__name__)

class ProgressTracker:
    """Enhanced progress tracker with real-time updates and callbacks."""

    def __init__(self, path: str, callback: Optional[Callable] = None) -> None:
        self.path = path
        self.callback = callback  # Callback for real-time updates
        self._lock = threading.Lock()  # Thread safety
        self._current_operation = ""
        self._start_time = None
        
    def load(self) -> Dict[str, Any]:
        """Return contents of the progress file or an empty dict."""
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to read progress file %s: %s", self.path, exc)
            return {}

    def get(self, key: str, default: int = 0) -> int:
        """Get a numeric progress value for ``key``."""
        data = self.load()
        try:
            return int(data.get(key, default))
        except Exception:
            return default

    def update(self, key: str, value: int, total: Optional[int] = None, 
               operation: str = "", details: str = "") -> None:
        """Enhanced update with progress percentage and operation details."""
        with self._lock:
            if not self.path:
                return
                
            data = self.load()
            data[key] = value
            
            # Add enhanced tracking info
            data[f"{key}_timestamp"] = datetime.now().isoformat()
            data[f"{key}_operation"] = operation
            data[f"{key}_details"] = details
            
            if total:
                data[f"{key}_total"] = total
                data[f"{key}_percentage"] = round((value / total) * 100, 2)
            
            # Calculate elapsed time if we have a start time
            if self._start_time:
                elapsed = time.time() - self._start_time
                data[f"{key}_elapsed"] = round(elapsed, 2)
                
                if total and value > 0:
                    # Estimate remaining time
                    rate = value / elapsed
                    remaining_items = total - value
                    estimated_remaining = remaining_items / rate if rate > 0 else 0
                    data[f"{key}_eta"] = round(estimated_remaining, 2)
            
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                    
                # Call callback for real-time updates
                if self.callback:
                    self.callback(key, value, total, operation, details)
                    
            except Exception as exc:
                logger.error("Failed to write progress file %s: %s", self.path, exc)

    def start_operation(self, operation_name: str) -> None:
        """Mark the start of an operation for timing."""
        self._current_operation = operation_name
        self._start_time = time.time()
        logger.info(f"Starting operation: {operation_name}")
        
        if self.callback:
            self.callback("operation_started", 0, None, operation_name, "")

    def finish_operation(self, operation_name: str) -> None:
        """Mark the completion of an operation."""
        if self._start_time:
            elapsed = time.time() - self._start_time
            logger.info(f"Completed operation: {operation_name} in {elapsed:.2f} seconds")
            
            if self.callback:
                self.callback("operation_completed", 100, 100, operation_name, 
                            f"Completed in {elapsed:.2f} seconds")
        
        self._start_time = None
        self._current_operation = ""

    def get_progress_summary(self) -> Dict[str, Any]:
        """Get a summary of all progress information."""
        data = self.load()
        summary = {}
        
        # Group related progress items
        for key, value in data.items():
            if not key.endswith(('_timestamp', '_operation', '_details', '_total', '_percentage', '_elapsed', '_eta')):
                base_key = key
                summary[base_key] = {
                    'current': value,
                    'total': data.get(f"{key}_total"),
                    'percentage': data.get(f"{key}_percentage", 0),
                    'operation': data.get(f"{key}_operation", ""),
                    'details': data.get(f"{key}_details", ""),
                    'elapsed': data.get(f"{key}_elapsed"),
                    'eta': data.get(f"{key}_eta"),
                    'timestamp': data.get(f"{key}_timestamp")
                }
        
        return summary

    def delete(self) -> None:
        """Delete the progress file if it exists."""
        if self.path and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass
