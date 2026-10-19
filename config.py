import os
import sys
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(f"[-] Файл конфигурации {CONFIG_PATH} не найден!")
        print("    Создайте config.yaml по шаблону.")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

cfg = load_config()
