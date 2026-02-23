"""
Script Executor.

Runs user-supplied scripts as pipeline steps. The script receives
asset data as input and returns structured data as output.

This enables deterministic lookups, API calls, data transformations,
or any other logic the pipeline doesn't need to know about.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from .base import ExecutorContext, StepExecutor, StepResult
from .registry import register_executor

console = Console()


@register_executor("script")
class ScriptExecutor(StepExecutor):
    """Execute user-supplied scripts."""

    async def execute(
        self,
        config: dict[str, Any],
        ctx: ExecutorContext,
    ) -> StepResult:
        """
        Execute a script step.

        Config:
            command: The command to run (e.g., "python scripts/lookup.py")
            args: Optional list of extra arguments
            input: How to pass data to the script:
                     "json" (default) - pipe asset data as JSON to stdin
                     "args" - pass asset fields as CLI arguments
                     "none" - no input
            output_format: How to parse stdout:
                             "json" (default) - parse as JSON
                             "text" - raw text
            timeout: Seconds before killing the process (default: 30)
            working_directory: Working dir for the script (default: pipeline base path)
        """
        import time
        start = time.time()

        command = config.get("command", "")
        extra_args = config.get("args", [])
        input_mode = config.get("input", "json")
        output_format = config.get("output_format", "json")
        timeout = config.get("timeout", 30)
        working_dir = config.get("working_directory")

        if not command:
            return StepResult(
                success=False,
                error="No command specified in script step config",
            )

        cmd_parts = command.split()

        if isinstance(extra_args, list):
            for arg in extra_args:
                cmd_parts.append(str(arg))

        if input_mode == "args" and ctx.asset:
            for key, value in ctx.asset.items():
                if isinstance(value, (str, int, float, bool)):
                    cmd_parts.extend([f"--{key}", str(value)])

        stdin_data = None
        if input_mode == "json":
            payload: dict[str, Any] = {}
            if ctx.asset:
                payload["asset"] = ctx.asset
            if ctx.context:
                payload["context"] = ctx.context
            if ctx.step_outputs:
                payload["step_outputs"] = _serialize_step_outputs(ctx.step_outputs)
            stdin_data = json.dumps(payload)

        cwd = working_dir or str(ctx.base_path)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=_build_env(ctx),
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(
                    input=stdin_data.encode() if stdin_data else None,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            return StepResult(
                success=False,
                error=f"Script timed out after {timeout}s: {command}",
            )
        except FileNotFoundError:
            return StepResult(
                success=False,
                error=f"Script not found: {cmd_parts[0]}",
            )

        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if process.returncode != 0:
            error_detail = stderr or stdout or f"exit code {process.returncode}"
            return StepResult(
                success=False,
                error=f"Script failed ({command}): {error_detail}",
            )

        if stderr:
            console.print(f"    [dim]script stderr: {stderr[:200]}[/dim]")

        if output_format == "json":
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as e:
                return StepResult(
                    success=False,
                    error=f"Script output is not valid JSON: {e}\nOutput: {stdout[:500]}",
                )

            if isinstance(parsed, dict):
                output = parsed
            else:
                output = {"content": parsed}
        else:
            output = {"content": stdout}

        duration = int((time.time() - start) * 1000)

        return StepResult(
            success=True,
            output=output,
            duration_ms=duration,
        )


def _serialize_step_outputs(step_outputs: dict[str, Any]) -> dict[str, Any]:
    """Make step outputs JSON-serializable by converting Path objects."""
    result = {}
    for key, value in step_outputs.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            result[key] = {
                k: str(v) if isinstance(v, Path) else v
                for k, v in value.items()
            }
        elif isinstance(value, Path):
            result[key] = str(value)
        elif isinstance(value, (str, int, float, bool, list, type(None))):
            result[key] = value
    return result


def _build_env(ctx: ExecutorContext) -> dict[str, str]:
    """Build environment variables for the script process."""
    import os

    env = os.environ.copy()
    env["ARTGEN_PIPELINE"] = ctx.pipeline_name
    env["ARTGEN_BASE_PATH"] = str(ctx.base_path)
    env["ARTGEN_STATE_DIR"] = str(ctx.state_dir)

    if ctx.asset:
        asset_id = ctx.asset.get("id", "")
        env["ARTGEN_ASSET_ID"] = str(asset_id)
        env["ARTGEN_ASSET_NAME"] = str(ctx.asset.get("name", ""))

    return env
