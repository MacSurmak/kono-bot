from typing import List, Dict, Set, Optional, Any
from google import genai
from config import cfg
from storage import record_gemini_key_stat, get_gemini_key_usage_counts


class GeminiRotator:
    def __init__(self):
        gemini_cfg = cfg["gemini"]
        self.keys_config: List[Dict[str, str]] = gemini_cfg["keys"]
        self.model_name: str = gemini_cfg["model"]
        self.thinking_level: str = gemini_cfg["thinking_level"]
        self.max_output_tokens: int = int(gemini_cfg["max_output_tokens"])

    def _get_sorted_keys(self, exclude_names: Set[str]) -> List[Dict[str, str]]:
        """Sorts available keys in ascending order of invocation counts (least used first)."""
        usage = get_gemini_key_usage_counts()
        available = [k for k in self.keys_config if k["name"] not in exclude_names]
        available.sort(key=lambda k: usage.get(k["name"], 0))
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

            usage_map = get_gemini_key_usage_counts()
            req_count = usage_map.get(key_name, 0) + 1

            print(
                f"[*] [Gemini API] Active account: '{key_name}' (call #{req_count})..."
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

                record_gemini_key_stat(key_name, success=True)
                print(f"[+] [Gemini API] Request succeeded with account '{key_name}'")
                return interaction.output_text.strip()

            except Exception as e:
                err_str = str(e).lower()
                is_quota_error = any(
                    marker in err_str
                    for marker in ("429", "quota", "resourceexhausted")
                )

                if is_quota_error:
                    print(
                        f"[⚠️ 429 Quota Exceeded] Key '{key_name}' depleted quota. Rotating..."
                    )
                    record_gemini_key_stat(key_name, success=False, is_rate_limit=True)
                    excluded_keys.add(key_name)
                    last_error = e
                else:
                    record_gemini_key_stat(key_name, success=False, is_rate_limit=False)
                    print(
                        f"[-] [Gemini API Error] Account '{key_name}' failed with unexpected error: {e}"
                    )
                    raise e

        raise RuntimeError(
            f"All available Gemini API keys exhausted their quotas. Last error: {last_error}"
        )


rotator = GeminiRotator()
