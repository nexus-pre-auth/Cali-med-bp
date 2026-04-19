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

# Supabase
SUPABASE_URL         = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# blueprintIQ rules API (replaces local JSON when set)
BLUEPRINTIQ_API_URL  = os.getenv("BLUEPRINTIQ_API_URL", "")   # e.g. https://api.blueprintiq.net
BLUEPRINTIQ_API_KEY  = os.getenv("BLUEPRINTIQ_API_KEY", "")

# Monitoring / alerting
ALERT_WEBHOOK_URL  = os.getenv("ALERT_WEBHOOK_URL", "")    # Slack or Teams incoming webhook
ALERT_EMAIL_FROM   = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_TO     = os.getenv("ALERT_EMAIL_TO", "")
ALERT_SMTP_HOST    = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT    = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_SMTP_USER    = os.getenv("ALERT_SMTP_USER", "")
ALERT_SMTP_PASS    = os.getenv("ALERT_SMTP_PASS", "")

# Batch processing
BATCH_MAX_WORKERS  = int(os.getenv("BATCH_MAX_WORKERS", "4"))
BATCH_CHUNK_SIZE   = int(os.getenv("BATCH_CHUNK_SIZE", "10"))
