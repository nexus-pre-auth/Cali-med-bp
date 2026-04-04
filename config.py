"""
Configuration settings for the Autonomous HCAI Compliance Engine.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root
BASE_DIR = Path(__file__).parent

# Data directories
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
CHROMA_DB_DIR = BASE_DIR / "chroma_db"

# Ensure directories exist
OUTPUT_DIR.mkdir(exist_ok=True)
CHROMA_DB_DIR.mkdir(exist_ok=True)

# Anthropic API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Compliance engine settings
HCAI_RULES_FILE = DATA_DIR / "hcai_rules.json"
TITLE24_REFS_FILE = DATA_DIR / "title24_references.json"
PINS_FILE = DATA_DIR / "pins_cans.json"

# Severity levels
SEVERITY_LEVELS = ["Critical", "High", "Medium", "Low"]

SEVERITY_COLORS = {
    "Critical": "#E53E3E",
    "High":     "#DD6B20",
    "Medium":   "#D69E2E",
    "Low":      "#38A169",
}

# RAG settings
RAG_TOP_K = 5
RAG_COLLECTION_NAME = "hcai_compliance_kb"

# Parser settings
SUPPORTED_EXTENSIONS = [".pdf", ".dwg", ".dxf"]
MAX_PDF_PAGES = 500
