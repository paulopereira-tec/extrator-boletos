"""
Validações para campos de boletos bancários (padrão FEBRABAN).
"""
import re
from itertools import cycle
from typing import Optional


# ---------------------------------------------------------------------------
# Algoritmos base
# ---------------------------------------------------------------------------

def _mod10(digits: str) -> int:
    """
    Módulo 10 — usado na validação de cada campo da linha digitável.
    Retorna o dígito verificador esperado (0-9).
    """
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n if n < 10 else n - 9
    return (10 - (total % 10)) % 10


def _mod11_febraban(digits: str) -> int:
    """
    Módulo 11 — usado na validação do código de barras.
    Pesos 2-9 cíclicos da direita para esquerda.
    Retorna 1 se resto for 0 ou 1 (regra FEBRABAN), caso contrário 11 - resto.
    """
    weights = cycle(range(2, 10))
    total = sum(int(d) * w for d, w in zip(reversed(digits), weights))
    remainder = total % 11
    return 1 if remainder in (0, 1) else 11 - remainder


# ---------------------------------------------------------------------------
# Validação do código de barras (44 dígitos)
# ---------------------------------------------------------------------------

def validate_codigo_barras(barcode: str) -> tuple[bool, Optional[str]]:
    """
    Valida o código de barras de 44 dígitos conforme FEBRABAN.
    O 5º dígito é o dígito verificador (mod 11).

    Retorna (válido, mensagem_de_erro).
    """
    digits = re.sub(r"\D", "", barcode)

    if len(digits) != 44:
        return False, f"Código de barras deve ter 44 dígitos; encontrado {len(digits)}."

    numero = digits[:4] + digits[5:]   # remove o dígito verificador (posição 4)
    check_expected = _mod11_febraban(numero)
    check_found = int(digits[4])

    if check_expected != check_found:
        return False, (
            f"Dígito verificador inválido: encontrado {check_found}, "
            f"esperado {check_expected}."
        )

    return True, None


# ---------------------------------------------------------------------------
# Validação da linha digitável (47 dígitos — boletos bancários)
# ---------------------------------------------------------------------------

def validate_linha_digitavel(linha: str) -> tuple[bool, Optional[str]]:
    """
    Valida a linha digitável bancária (47 dígitos) conforme FEBRABAN:
      - Campo 1 (pos 0-9):  9 dígitos + dígito verificador mod 10
      - Campo 2 (pos 10-20): 10 dígitos + dígito verificador mod 10
      - Campo 3 (pos 21-31): 10 dígitos + dígito verificador mod 10
      - Campo 4 (pos 32): dígito verificador do código de barras (mod 11)

    Retorna (válido, mensagem_de_erro).
    """
    digits = re.sub(r"\D", "", linha)

    if len(digits) != 47:
        return False, (
            f"Linha digitável bancária deve ter 47 dígitos; encontrado {len(digits)}. "
            "Linhas de concessionárias (48 dígitos) não são verificadas."
        )

    errors = []

    # Campo 1
    expected = _mod10(digits[0:9])
    if expected != int(digits[9]):
        errors.append(
            f"Campo 1: dígito verificador inválido (encontrado {digits[9]}, esperado {expected})"
        )

    # Campo 2
    expected = _mod10(digits[10:20])
    if expected != int(digits[20]):
        errors.append(
            f"Campo 2: dígito verificador inválido (encontrado {digits[20]}, esperado {expected})"
        )

    # Campo 3
    expected = _mod10(digits[21:31])
    if expected != int(digits[31]):
        errors.append(
            f"Campo 3: dígito verificador inválido (encontrado {digits[31]}, esperado {expected})"
        )

    if errors:
        return False, "; ".join(errors)

    return True, None


# ---------------------------------------------------------------------------
# Validação de CNPJ
# ---------------------------------------------------------------------------

def validate_cnpj(cnpj: str) -> tuple[bool, Optional[str]]:
    """
    Valida CNPJ com dois dígitos verificadores.
    Retorna (válido, mensagem_de_erro).
    """
    digits = re.sub(r"\D", "", cnpj)

    if len(digits) != 14:
        return False, f"CNPJ deve ter 14 dígitos; encontrado {len(digits)}."

    if len(set(digits)) == 1:
        return False, "CNPJ inválido (todos os dígitos iguais)."

    # Primeiro dígito verificador
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    s = sum(int(d) * w for d, w in zip(digits[:12], w1))
    r = s % 11
    d1 = 0 if r < 2 else 11 - r

    if int(digits[12]) != d1:
        return False, "CNPJ inválido (primeiro dígito verificador incorreto)."

    # Segundo dígito verificador
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    s = sum(int(d) * w for d, w in zip(digits[:13], w2))
    r = s % 11
    d2 = 0 if r < 2 else 11 - r

    if int(digits[13]) != d2:
        return False, "CNPJ inválido (segundo dígito verificador incorreto)."

    return True, None


# ---------------------------------------------------------------------------
# Formatação de datas e valores
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> str:
    """
    Converte data de DD/MM/YYYY para YYYY-MM-DD.
    Retorna a string original se não conseguir converter.
    """
    from datetime import datetime
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str


def parse_valor(valor_str: str) -> Optional[float]:
    """
    Converte valor brasileiro (1.250,00) para float (1250.0).
    Retorna None se não conseguir converter.
    """
    try:
        # Remove separador de milhar (.) e troca vírgula decimal por ponto
        cleaned = valor_str.replace(".", "").replace(",", ".")
        return round(float(cleaned), 2)
    except (ValueError, AttributeError):
        return None
