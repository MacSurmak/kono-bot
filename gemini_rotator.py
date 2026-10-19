import sqlite3
from typing import List, Dict, Any, Optional
from google import genai
from config import cfg

DB_PATH = "iiko_matcher.db"

def init_stats_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gemini_key_stats (
                key_name TEXT PRIMARY KEY,
                total_requests INTEGER DEFAULT 0,
                successful_requests INTEGER DEFAULT 0,
                rate_limit_hits INTEGER DEFAULT 0,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

init_stats_db()

class GeminiRotator:
    def __init__(self):
        gemini_cfg = cfg.get("gemini", {})
        self.keys_config: List[Dict[str, str]] = gemini_cfg.get("keys", [])
        self.model_name = gemini_cfg.get("model", "gemini-3.8-flash")
        self.thinking_level = gemini_cfg.get("thinking_level", "medium")

        if not self.keys_config:
            raise ValueError("[-] В config.yaml не указан ни один ключ в секции gemini.keys!")

    def _get_key_usage_counts(self) -> Dict[str, int]:
        """Возвращает словарь {key_name: total_requests} из базы данных"""
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT key_name, total_requests FROM gemini_key_stats")
            return dict(cur.fetchall())

    def _get_sorted_keys(self, exclude_names: set) -> List[Dict[str, str]]:
        """Сортирует доступные ключи по возрастанию числа запросов (Least Used)"""
        usage = self._get_key_usage_counts()
        available = [k for k in self.keys_config if k["name"] not in exclude_names]
        # Сортируем: сначала те, у кого меньше запросов
        available.sort(key=lambda k: usage.get(k["name"], 0))
        return available

    def _record_stat(self, key_name: str, success: bool, is_rate_limit: bool = False):
        """Записывает в БД факт использования ключа"""
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO gemini_key_stats (key_name, total_requests, successful_requests, rate_limit_hits, last_used_at)
                VALUES (?, 1, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key_name) DO UPDATE SET
                    total_requests = total_requests + 1,
                    successful_requests = successful_requests + ?,
                    rate_limit_hits = rate_limit_hits + ?,
                    last_used_at = CURRENT_TIMESTAMP
            """, (
                key_name,
                1 if success else 0,
                1 if is_rate_limit else 0,
                1 if success else 0,
                1 if is_rate_limit else 0
            ))

    def execute_interaction(self, input_payload: list) -> str:
        """
        Выполняет запрос с ротацией и автопереключением на следующий ключ при 429
        """
        excluded = set()
        last_error = None

        while len(excluded) < len(self.keys_config):
            candidates = self._get_sorted_keys(excluded)
            if not candidates:
                break

            current = candidates[0]
            key_name = current["name"]
            api_key = current["api_key"]

            usage_map = self._get_key_usage_counts()
            req_num = usage_map.get(key_name, 0) + 1

            print(f"[*] [Gemini API] Выбран аккаунт: '{key_name}' (запрос #{req_num} по счетчику)...")

            try:
                ai_client = genai.Client(api_key=api_key)
                interaction = ai_client.interactions.create(
                    model=self.model_name,
                    input=input_payload,
                    generation_config={
                        'max_output_tokens': 65536,
                        'thinking_level': self.thinking_level
                    }
                )

                # Успешный запрос
                self._record_stat(key_name, success=True)
                print(f"[+] [Gemini API] Успешный ответ от аккаунта '{key_name}'")
                return interaction.output_text.strip()

            except Exception as e:
                err_str = str(e).lower()
                is_429 = "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str

                if is_429:
                    print(f"[⚠️ 429 RATE LIMIT] Аккаунт '{key_name}' исчерпал квоту! Переключаемся на следующий...")
                    self._record_stat(key_name, success=False, is_rate_limit=True)
                    excluded.add(key_name)
                    last_error = e
                else:
                    self._record_stat(key_name, success=False, is_rate_limit=False)
                    print(f"[-] Ошибка API на ключе '{key_name}': {e}")
                    raise e

        raise RuntimeError(f"[-] Все доступные ключи Gemini исчерпали свои лимиты! Последняя ошибка: {last_error}")

rotator = GeminiRotator()
