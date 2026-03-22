"""
Logging configuration for ArtGen pipelines.

Sets up structured logging that:
  - Keeps the CLI output clean (suppresses third-party noise)
  - Optionally writes detailed logs to a file
  - Auto-logs to the pipeline's state directory
  - Quiets known noisy loggers (litellm, httpcore, httpx)
"""

import logging
import sys
from pathlib import Path

# Known noisy third-party loggers to suppress
NOISY_LOGGERS = [
    "LiteLLM",
    "litellm",
    "litellm.litellm_core_utils",
    "litellm.litellm_core_utils.logging_worker",
    "litellm.utils",
    "litellm.cost_calculator",
    "openai",
    "openai._base_client",
    "openai.resources",
    "httpcore",
    "httpx",
    "httpcore.http11",
    "httpcore.connection",
    "urllib3",
    "urllib3.connectionpool",
    "google.auth",
    "google.auth.transport",
    "google.api_core",
    "grpc",
    "PIL",
    "google_genai",
    "google_genai._api_client",
    "google_genai.models",
]

# Our own loggers (these get more permissive levels)
ARTGEN_LOGGERS = [
    "backend",
    "pipeline",
    "providers",
    "app",
]


def setup_logging(
    verbose: bool = False,
    log_file: Path | str | None = None,
    state_dir: Path | str | None = None,
) -> Path | None:
    """
    Configure logging for an ArtGen run.

    Args:
        verbose: If True, show more detail on console (DEBUG for our code,
                 WARNING for third-party). If False, suppress most console
                 logging (only CRITICAL from third-party, WARNING from ours).
        log_file: Explicit log file path. If provided, all DEBUG-level logs
                  (including third-party) are written here.
        state_dir: Pipeline state directory. If provided and no explicit
                   log_file, a run log is auto-created at
                   {state_dir}/run.log.

    Returns:
        Path to the log file if one was created, or None.
    """
    # Determine the actual log file path
    actual_log_file: Path | None = None
    if log_file:
        actual_log_file = Path(log_file)
    elif state_dir:
        actual_log_file = Path(state_dir) / "run.log"

    # Reset root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove any existing handlers to avoid duplicate output
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # --- Console handler (stderr) ---
    # Use a simple formatter that doesn't duplicate Rich's output
    console_handler = logging.StreamHandler(sys.stderr)
    if verbose:
        console_handler.setLevel(logging.DEBUG)
    else:
        # In non-verbose mode, only show warnings and above on console
        console_handler.setLevel(logging.WARNING)

    console_fmt = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    root.addHandler(console_handler)

    # --- File handler (if requested) ---
    if actual_log_file:
        actual_log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(actual_log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_fmt)
        root.addHandler(file_handler)

    # --- Suppress noisy third-party loggers ---
    for logger_name in NOISY_LOGGERS:
        lib_logger = logging.getLogger(logger_name)
        if verbose:
            # Even in verbose mode, only show warnings from third-party
            lib_logger.setLevel(logging.WARNING)
        else:
            # In normal mode, fully suppress (only CRITICAL)
            lib_logger.setLevel(logging.CRITICAL)

    # --- Set levels for our own loggers ---
    for logger_name in ARTGEN_LOGGERS:
        our_logger = logging.getLogger(logger_name)
        if verbose:
            our_logger.setLevel(logging.DEBUG)
        else:
            our_logger.setLevel(logging.WARNING)

    return actual_log_file
