"""Shared Jinja2 template environment (single instance, absolute path)."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=_TEMPLATES_DIR)
