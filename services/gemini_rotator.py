import time
from typing import List, Dict, Set, Optional, Any
import os
import redis
from google import genai
from loguru import logger
from config import cfg

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL or not REDIS_URL.strip():
    raise RuntimeError("CRITICAL CONFIGURATION ERROR: 'REDIS_URL' environment variable is not set.")


class GeminiRotator:
    def __init__(self):
        gemini_cfg = cfg["gemini"]
        self.keys_config: List[Dict[str, str]] = gemini_cfg["keys"]
        self.model_name: str = gemini_cfg["model"]
        self.thinking_level: str = gemini_cfg["thinking_level"]
        self.max_output_tokens: int = int(gemini_cfg["max_output_tokens"])

        try:
            self._redis = redis.Redis.from_url(REDIS_URL.strip(), decode_responses=True)
            self._redis.ping()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Redis for Gemini rotator: {e}") from e

    def _get_key_usage(self, key_name: str) -> int:
        try:
            val = self._redis.get(f"gemini:key:{key_name}:requests")
            if val is not None:
                return int(val)
            return 0
        except Exception as e:
            logger.warning(f"Failed to read usage stats for key '{key_name}' from Redis: {e}")
            return 0

    def _record_key_stat(
        self, key_name: str, success: bool, is_rate_limit: bool = False
    ) -> None:
        try:
            self._redis.incr(f"gemini:key:{key_name}:requests")
            if is_rate_limit:
                self._redis.incr(f"gemini:key:{key_name}:rate_limits")
        except Exception as e:
            logger.warning(f"Failed to record telemetry for key '{key_name}' in Redis: {e}")

    def _get_sorted_keys(self, exclude_names: Set[str]) -> List[Dict[str, str]]:
        """Sorts available keys in ascending order of invocation counts (least used first)."""
        available = [k for k in self.keys_config if k["name"] not in exclude_names]
        available.sort(key=lambda k: self._get_key_usage(k["name"]))
        return available

    def execute_interaction(
        self, input_payload: list, schema: Optional[Any] = None
    ) -> str:
        """Executes LLM call with transparent least-used rotation, 429 failover, and optional structured schema."""
        excluded_keys: Set[str] = set()
        last_error = None

        while len(excluded_keys) < len(self.keys_config):
            candidates = self._get_sorted_keys(excluded_keys)
            if not candidates:
                break

            current_key = candidates[0]
            key_name = current_key["name"]
            api_key = current_key["api_key"]

            req_count = self._get_key_usage(key_name) + 1

            logger.info(
                f"[Gemini API] Active account: '{key_name}' (call #{req_count})..."
            )

            try:
                ai_client = genai.Client(api_key=api_key)

                create_kwargs = {
                    "model": self.model_name,
                    "input": input_payload,
                    "generation_config": {
                        "max_output_tokens": self.max_output_tokens,
                        "thinking_level": self.thinking_level,
                    },
                }

                if schema is not None:
                    # Export Pydantic model to JSON schema dict required by Google Interactions API
                    json_schema = (
                        schema.model_json_schema()
                        if hasattr(schema, "model_json_schema")
                        else schema
                    )
                    create_kwargs["response_format"] = {
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": json_schema,
                    }

                interaction = ai_client.interactions.create(**create_kwargs)

                self._record_key_stat(key_name, success=True)
                logger.info(f"[Gemini API] Request succeeded with account '{key_name}'")
                return interaction.output_text.strip()

            except Exception as e:
                err_str = str(e).lower()
                is_quota_error = any(
                    marker in err_str
                    for marker in ("429", "quota", "resourceexhausted")
                )
                is_transient_error = any(
                    marker in err_str
                    for marker in (
                        "503",
                        "500",
                        "502",
                        "504",
                        "unavailable",
                        "overloaded",
                        "deadline",
                        "timeout",
                    )
                )

                if is_quota_error:
                    logger.warning(
                        f"[429 Quota Exceeded] Account '{key_name}' depleted quota. Rotating..."
                    )
                    self._record_key_stat(key_name, success=False, is_rate_limit=True)
                    excluded_keys.add(key_name)
                    last_error = e
                elif is_transient_error:
                    logger.warning(
                        f"[Google Cloud Transient Error] Account '{key_name}' received temporary upstream error: {e}. "
                        "Backing off for 2.0s and rotating to next account..."
                    )
                    self._record_key_stat(key_name, success=False, is_rate_limit=False)
                    excluded_keys.add(key_name)
                    time.sleep(2.0)
                    last_error = e
                else:
                    self._record_key_stat(key_name, success=False, is_rate_limit=False)
                    logger.error(
                        f"[Gemini API Fatal Error] Account '{key_name}' failed with unexpected error: {e}"
                    )
                    raise e

        raise RuntimeError(
            f"All available Gemini API keys ({len(self.keys_config)}) exhausted quotas or encountered transient errors. Last error: {last_error}"
        )


rotator = GeminiRotator()
