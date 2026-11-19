"""
Gerencia o estado de ativação da API.

O estado é persistido em um arquivo de flag no container para sobreviver
a reloads do uvicorn (mas será resetado para 'ativo' a cada novo container,
a menos que você monte um volume no path STATE_FILE).
"""
import os

STATE_FILE = os.environ.get("STATE_FILE", "/tmp/api_state.flag")
_DEFAULT_STATE = 1  # 1 = ativo, 0 = desligado


def _read() -> int:
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return _DEFAULT_STATE


def _write(value: int) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(str(value))


def get_state() -> int:
    return _read()


def set_state(value: int) -> None:
    if value not in (0, 1):
        raise ValueError("O parâmetro 'start' deve ser 0 ou 1.")
    _write(value)


def is_active() -> bool:
    return _read() == 1
