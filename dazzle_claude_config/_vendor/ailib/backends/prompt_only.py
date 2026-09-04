"""Prompt-only backend -- saves the prompt to a file for manual use.

Unlike the other backends, the output directory is configurable per-tool
since different tools save prompts to different locations.
"""

from datetime import datetime
from pathlib import Path

# Default output directory -- overridden by set_output_dir()
_output_dir = None


def set_output_dir(path):
    """Set the directory where prompt files are saved.

    Each tool should call this before invoking analyze() with
    backend_name="prompt-only":

        from wtf_windows.lib.ai.backends import prompt_only
        prompt_only.set_output_dir(Path.home() / ".wtf-locked" / "ai")
    """
    global _output_dir
    _output_dir = Path(path)


def _get_output_dir():
    """Get the prompt output directory."""
    out_dir = _output_dir or (Path.home() / ".wtf-windows" / "ai")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def is_available():
    """Always available."""
    return True


def invoke(prompt, verbose=False, timeout=120):
    """
    Save prompt to a file instead of invoking an AI.

    Returns: (success: bool, output: str)
    """
    out_dir = _get_output_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    prompt_file = out_dir / f"prompt_{timestamp}.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    return False, (
        f"Prompt saved to: {prompt_file}\n"
        "Paste this prompt into an AI assistant for analysis."
    )
