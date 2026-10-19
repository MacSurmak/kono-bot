import os
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

class ConfigurationError(Exception):
    """Raised when configuration file is missing or invalid."""

def load_and_validate_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise ConfigurationError(f"Configuration file not found at: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ConfigurationError("Configuration file must contain a valid YAML mapping")

    # Validate iiko section
    iiko = config.get("iiko")
    if not isinstance(iiko, dict):
        raise ConfigurationError("Missing or invalid 'iiko' section in config.yaml")
    for field in ("base_url", "login", "password"):
        if not iiko.get(field):
            raise ConfigurationError(f"Missing required iiko parameter: '{field}'")

    # Validate gemini section
    gemini = config.get("gemini")
    if not isinstance(gemini, dict):
        raise ConfigurationError("Missing or invalid 'gemini' section in config.yaml")
    for field in ("model", "thinking_level", "max_output_tokens"):
        if field not in gemini:
            raise ConfigurationError(f"Missing required gemini parameter: '{field}'")

    keys = gemini.get("keys")
    if not isinstance(keys, list) or len(keys) == 0:
        raise ConfigurationError("Section 'gemini.keys' must contain at least one API key definition")

    for idx, key_entry in enumerate(keys):
        if not isinstance(key_entry, dict) or not key_entry.get("name") or not key_entry.get("api_key"):
            raise ConfigurationError(f"Invalid gemini key entry at index {idx}: must contain 'name' and 'api_key'")

    return config

cfg = load_and_validate_config()

# Single Source of Truth for allowed stores and keyword mappings
STORES_CONFIG = {
    "4841e49a-61b4-4f34-b51c-7cfb3ccad7ac": {
        "name": "АЭРОПОРТ",
        "keywords": ["аэропорт", "ленинградский", "ленинградка", "д. 62", "дом 62"]
    },
    "62b795dd-f0e2-4d3b-b354-5ff194b8dcd9": {
        "name": "ОКТЯБРЬСКАЯ",
        "keywords": ["октябрьская", "серпуховская", "замоскворечье", "8/7", "большая серпуховская"]
    }
}
ALLOWED_STORES = {store_id: data["name"] for store_id, data in STORES_CONFIG.items()}
STORE_KEYWORDS = {store_id: data["keywords"] for store_id, data in STORES_CONFIG.items()}
