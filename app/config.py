import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.yaml"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bounces.db"

DATA_DIR.mkdir(exist_ok=True)


def load_config() -> dict:
    """Load configuration from YAML file."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return yaml.safe_load(f)
    return {}


def save_config(config: dict):
    """Save configuration to YAML file."""
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_config() -> dict:
    """Get merged config from file and environment variables."""
    config = load_config()

    # Override with environment variables
    if os.getenv("POSTAL_API_KEY"):
        config.setdefault("postal", {})["api_key"] = os.getenv("POSTAL_API_KEY")
    if os.getenv("POSTAL_API_URL"):
        config.setdefault("postal", {})["api_url"] = os.getenv("POSTAL_API_URL")
    if os.getenv("CHATWOOT_API_TOKEN"):
        config.setdefault("chatwoot", {})["api_token"] = os.getenv("CHATWOOT_API_TOKEN")
    if os.getenv("CHATWOOT_API_URL"):
        config.setdefault("chatwoot", {})["api_url"] = os.getenv("CHATWOOT_API_URL")
    if os.getenv("BOUNCE_SENDER_EMAIL"):
        config.setdefault("notifications", {})["sender_email"] = os.getenv("BOUNCE_SENDER_EMAIL")

    return config


# Expiry days by bounce type and source
EXPIRY_DAYS = {
    "ses_permanent": 365,
    "ses_transient": 30,
    "ses_complaint": 180,
    "postal_bounce": 30,
    "postfix_hard": 365,
    "postfix_soft": 30,
}
