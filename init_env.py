"""
init_env.py
Crea/actualiza .env generando MASTER_KEY y SESSION_SECRET si están vacías.
No sobrescribe valores que ya existan.
Uso:  python init_env.py
"""
import base64
import os
import secrets
from pathlib import Path

ENV = Path(".env")
EXAMPLE = Path(".env.example")

GENERATED = {
    "MASTER_KEY": lambda: base64.b64encode(os.urandom(32)).decode(),
    "SESSION_SECRET": lambda: secrets.token_urlsafe(48),
}
DEFAULTS = {
    "MAX_FILE_MB": "25",
    "MAX_FILES_PER_CASE": "40",
    "MAX_ZIP_UNCOMPRESSED_MB": "300",
    "MAX_ZIP_CONTAINER_MB": "200",
}


def is_blank(value: str) -> bool:
    return value.split("#", 1)[0].strip() == ""


if not ENV.exists():
    ENV.write_text(
        EXAMPLE.read_text(encoding="utf-8") if EXAMPLE.exists() else "",
        encoding="utf-8",
    )

seen = set()
out = []
for line in ENV.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if s and not s.startswith("#") and "=" in s:
        key, value = s.split("=", 1)
        key = key.strip()
        if key in GENERATED:
            seen.add(key)
            if is_blank(value):
                line = f"{key}={GENERATED[key]()}"
                print(f"[nuevo] {key} generada")
            else:
                print(f"[ya existe] {key}")
        elif key in DEFAULTS:
            seen.add(key)
    out.append(line)

for key, gen in GENERATED.items():
    if key not in seen:
        out.append(f"{key}={gen()}")
        print(f"[nuevo] {key} generada")
for key, val in DEFAULTS.items():
    if key not in seen:
        out.append(f"{key}={val}")

ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
print("Listo: .env actualizado (no lo subas a git ni lo compartas).")