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

    # Validate iiko section (base_url is network-wide; credentials are authenticated per-user)
    iiko = config.get("iiko")
    if not isinstance(iiko, dict):
        raise ConfigurationError("Missing or invalid 'iiko' section in config.yaml")
    if not iiko.get("base_url"):
        raise ConfigurationError("Missing required iiko parameter: 'base_url'")

    catalog_filter = iiko.get("catalog_filter")
    if not isinstance(catalog_filter, dict):
        raise ConfigurationError(
            "Missing or invalid 'iiko.catalog_filter' section in config.yaml"
        )
    if "include_groups" not in catalog_filter or not isinstance(
        catalog_filter["include_groups"], list
    ):
        raise ConfigurationError(
            "Missing or invalid 'iiko.catalog_filter.include_groups' list in config.yaml"
        )
    if "exclude_groups" not in catalog_filter or not isinstance(
        catalog_filter["exclude_groups"], list
    ):
        raise ConfigurationError(
            "Missing or invalid 'iiko.catalog_filter.exclude_groups' list in config.yaml"
        )

    # Validate gemini section
    gemini = config.get("gemini")
    if not isinstance(gemini, dict):
        raise ConfigurationError("Missing or invalid 'gemini' section in config.yaml")
    for field in ("model", "thinking_level", "max_output_tokens"):
        if field not in gemini:
            raise ConfigurationError(f"Missing required gemini parameter: '{field}'")

    keys = gemini.get("keys")
    if not isinstance(keys, list) or len(keys) == 0:
        raise ConfigurationError(
            "Section 'gemini.keys' must contain at least one API key definition"
        )

    for idx, key_entry in enumerate(keys):
        if (
            not isinstance(key_entry, dict)
            or not key_entry.get("name")
            or not key_entry.get("api_key")
        ):
            raise ConfigurationError(
                f"Invalid gemini key entry at index {idx}: must contain 'name' and 'api_key'"
            )

    # Validate telegram section
    telegram = config.get("telegram")
    if not isinstance(telegram, dict):
        raise ConfigurationError("Missing or invalid 'telegram' section in config.yaml")
    if not telegram.get("bot_token"):
        raise ConfigurationError("Missing required telegram parameter: 'bot_token'")
    if not telegram.get("admin_id") and not telegram.get("admin_ids"):
        raise ConfigurationError(
            "Missing required telegram parameter: 'admin_id' or 'admin_ids'"
        )

    return config


cfg = load_and_validate_config()


def get_admin_ids() -> set[int]:
    """Retrieves set of admin Telegram IDs from configuration with fail-fast validation."""
    tg = cfg.get("telegram")
    if not isinstance(tg, dict):
        raise ConfigurationError("Missing or invalid 'telegram' configuration section")

    admin_ids = set()
    if "admin_ids" in tg and isinstance(tg["admin_ids"], list):
        admin_ids.update(int(x) for x in tg["admin_ids"] if str(x).isdigit())
    if "admin_id" in tg and tg["admin_id"] and str(tg["admin_id"]).isdigit():
        admin_ids.add(int(tg["admin_id"]))

    if not admin_ids:
        raise ConfigurationError(
            "At least one valid integer admin Telegram ID must be configured in 'telegram.admin_ids'"
        )
    return admin_ids


# ==============================================================================
# ARCHITECTURAL INVARIANT: ZERO MAGIC NUMBERS & DECLARATIVE SYSTEM CONSTANTS
#
# RULE: All algorithmic thresholds, buffer sizes, pagination limits, and TTL
# durations must be explicitly declared as typed constants in this section.
#
# FORBIDDEN:
# - Embedding inline numeric literals (magic numbers like 6, 8, 600, 3600)
#   directly into SQL queries, slice limits, or API calls across the codebase.
# - Providing silent fallback defaults (e.g. `or "localhost"`) if an environment
#   variable is required for operational integrity.
# ==============================================================================

# Pagination limits
PAGE_SIZE_USERS = 6
PAGE_SIZE_MAPPINGS = 6
PAGE_SIZE_STORES = 6
PAGE_SIZE_INVOICE_STORES = 5
PAGE_SIZE_REVIEW_ITEMS = 8

# Cache and lifecycle durations
CACHE_TTL_CATALOG_SECONDS = 600.0
CACHE_TTL_SUPPLIERS_SECONDS = 600.0
SESSION_CLEANUP_TTL_SECONDS = 3600
DEFAULT_THROTTLING_RATE_LIMIT = 0.5
