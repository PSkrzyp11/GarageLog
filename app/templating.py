from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Jinja2Templates enables autoescaping for .html files, which protects against XSS.
templates = Jinja2Templates(directory=TEMPLATES_DIR)
