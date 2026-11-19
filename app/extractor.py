"""
Extração própria de dados de boletos bancários a partir de PDFs.

Estratégia:
  1. pdfplumber  → extrai texto nativo do PDF
  2. OCR fallback → se o texto for escasso (PDF escaneado), usa pdf2image + pytesseract
  3. Regex FEBRABAN → localiza cada campo padronizado
  4. LLM opcional → enriquecimento pós-extração
"""

import base64
import logging
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

import pdfplumber
from .validators import (
    validate_codigo_barras,
    validate_linha_digitavel,
    validate_cnpj,
    parse_date,
    parse_valor,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OCR fallback (opcional — instalado no Dockerfile)
# ---------------------------------------------------------------------------
try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("pdf2image/pytesseract não disponíveis. Fallback OCR desativado.")


# ---------------------------------------------------------------------------
# Padrões FEBRABAN
# ---------------------------------------------------------------------------

# Linha digitável: dois formatos principais
#   Convênio/boleto bancário: 47 dígitos com pontos e espaços
#   Concessionárias/utilities: 48 dígitos
_LINHA_DIGITAVEL = re.compile(
    r"\b(\d{5}[\.\s]\d{5}[\.\s]\d{5}[\.\s]\d{6}[\.\s]\d{5}[\.\s]\d{6}[\.\s]\d[\.\s]\d{14})"
    r"|\b(\d{10}[\.\s]\d{10}[\.\s]\d{10}[\.\s]\d{10}[\.\s]\d{8})"  # utilities
    r"|\b(\d{47,48})\b",
    re.DOTALL,
)

# Código de barras: exatamente 44 dígitos consecutivos
_CODIGO_BARRAS = re.compile(r"\b(\d{44})\b")

# Valor: próximo a palavras-chave de valor
_VALOR = re.compile(
    r"(?:valor\s+(?:do\s+)?(?:documento|cobrado|nominal|boleto|título)?[\s:=]*)"
    r"R?\$?\s*([\d\.]+,\d{2})",
    re.IGNORECASE,
)
_VALOR_FALLBACK = re.compile(r"R\$\s*([\d\.]+,\d{2})")

# Datas DD/MM/AAAA
_DATA = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_DATA_VENCIMENTO = re.compile(
    r"(?:vencimento|venc\.?|data\s+de\s+vencimento)[\s:=]*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_DATA_EMISSAO = re.compile(
    r"(?:emiss[aã]o|data\s+de\s+emiss[aã]o|emitido\s+em)[\s:=]*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)

# CNPJ e CPF
_CNPJ = re.compile(r"\b(\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\s]?\d{4}[-\s]?\d{2})\b")
_CPF  = re.compile(r"\b(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?\d{2})\b")

# Nosso número
_NOSSO_NUMERO = re.compile(
    r"(?:nosso\s+n[uú]mero|n\.?\s*n\.?)[\s:=]*([0-9\-\/\.]+)",
    re.IGNORECASE,
)

# Agência / conta
_AGENCIA = re.compile(
    r"(?:ag[eê]ncia\s*[\/\-]?\s*c[oó]digo\s*(?:do\s+)?benefici[aá]rio|ag[eê]ncia\s*[\/]?\s*conta)[\s:=]*([0-9\-\. \/]+)",
    re.IGNORECASE,
)

# Banco (código 3 dígitos no início da linha digitável)
_BANCOS: Dict[str, str] = {
    "001": "Banco do Brasil",
    "033": "Santander",
    "077": "Banco Inter",
    "104": "Caixa Econômica Federal",
    "237": "Bradesco",
    "341": "Itaú",
    "356": "BMG",
    "389": "Mercantil",
    "422": "Safra",
    "748": "Sicredi",
    "756": "Sicoob",
    "336": "C6 Bank",
    "655": "Votorantim",
    "318": "BMG",
    "212": "Banco Original",
    "260": "Nu Pagamentos (Nubank)",
    "290": "PagSeguro",
    "323": "Mercado Pago",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_number(value: str) -> str:
    """Remove separadores de formatação, mantendo apenas dígitos e vírgula/ponto decimal."""
    return re.sub(r"[^\d,\.]", "", value).strip()


def _extract_text_native(path: str) -> str:
    """Extrai texto nativo do PDF com pdfplumber."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\n".join(pages)


def _extract_text_ocr(path: str) -> str:
    """Fallback OCR com pdf2image + pytesseract (para PDFs escaneados)."""
    if not OCR_AVAILABLE:
        return ""
    try:
        images = convert_from_path(path, dpi=300)
        texts = []
        for img in images:
            texts.append(
                pytesseract.image_to_string(img, lang="por", config="--psm 6")
            )
        return "\n".join(texts)
    except Exception as exc:
        logger.warning("Falha no OCR: %s", exc)
        return ""


def _get_text(path: str) -> tuple[str, str]:
    """
    Retorna (texto, método_usado).
    Usa OCR como fallback se o texto nativo for insuficiente.
    """
    text = _extract_text_native(path)
    # Heurística: se extraiu menos de 50 chars úteis, provavelmente é escaneado
    if len(text.strip()) < 50:
        logger.info("Texto nativo insuficiente (%d chars), tentando OCR.", len(text.strip()))
        ocr_text = _extract_text_ocr(path)
        if len(ocr_text.strip()) > len(text.strip()):
            return ocr_text, "ocr"
    return text, "native"


# ---------------------------------------------------------------------------
# Extração de campos
# ---------------------------------------------------------------------------

def _extract_boleto_fields(text: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}

    # ── Linha digitável ──────────────────────────────────────────────────────
    m = _LINHA_DIGITAVEL.search(text)
    if m:
        raw = next(g for g in m.groups() if g)
        linha = re.sub(r"[\s]", " ", raw).strip()
        fields["linha_digitavel"] = linha

        # Código de barras: derivado da linha digitável (44 dígitos sem formatação)
        digits_only = re.sub(r"\D", "", linha)
        if len(digits_only) >= 44:
            fields["codigo_barras"] = digits_only[:44]

            # Banco a partir dos 3 primeiros dígitos
            banco_code = digits_only[:3]
            fields["banco_codigo"] = banco_code
            fields["banco"] = _BANCOS.get(banco_code, f"Banco {banco_code}")

    # ── Código de barras direto (se não veio da linha digitável) ─────────────
    if "codigo_barras" not in fields:
        m = _CODIGO_BARRAS.search(text)
        if m:
            fields["codigo_barras"] = m.group(1)
            banco_code = m.group(1)[:3]
            fields["banco_codigo"] = banco_code
            fields["banco"] = _BANCOS.get(banco_code, f"Banco {banco_code}")

    # ── Valor (retornado como decimal) ───────────────────────────────────────
    m = _VALOR.search(text)
    raw_valor = m.group(1) if m else None
    if not raw_valor:
        m = _VALOR_FALLBACK.search(text)
        raw_valor = m.group(1) if m else None
    if raw_valor:
        parsed = parse_valor(_clean_number(raw_valor))
        fields["valor"] = parsed if parsed is not None else _clean_number(raw_valor)

    # ── Datas (retornadas em YYYY-MM-DD) ─────────────────────────────────────
    m = _DATA_VENCIMENTO.search(text)
    if m:
        fields["data_vencimento"] = parse_date(m.group(1))
    else:
        dates = _DATA.findall(text)
        if dates:
            fields["data_vencimento"] = parse_date(dates[0])

    m = _DATA_EMISSAO.search(text)
    if m:
        fields["data_emissao"] = parse_date(m.group(1))
    elif len(_DATA.findall(text)) > 1:
        fields["data_emissao"] = parse_date(_DATA.findall(text)[1])

    # ── CNPJ / CPF ───────────────────────────────────────────────────────────
    cnpjs = _CNPJ.findall(text)
    cpfs  = _CPF.findall(text)

    # Filtra CPFs que são na verdade parte de um CNPJ
    cpfs = [c for c in cpfs if not any(c.replace(".", "").replace("-", "") in
            cnpj.replace(".", "").replace("/", "").replace("-", "") for cnpj in cnpjs)]

    if cnpjs:
        fields["cnpj_beneficiario"] = cnpjs[0]
    if len(cnpjs) > 1:
        fields["cnpj_pagador"] = cnpjs[1]
    if cpfs:
        fields["cpf_pagador"] = cpfs[0]

    # ── Nosso número ─────────────────────────────────────────────────────────
    m = _NOSSO_NUMERO.search(text)
    if m:
        fields["nosso_numero"] = m.group(1).strip()

    # ── Agência / conta beneficiário ─────────────────────────────────────────
    m = _AGENCIA.search(text)
    if m:
        fields["agencia_conta"] = m.group(1).strip()

    # ── Beneficiário e Pagador (linhas próximas a labels) ────────────────────
    _extract_name_fields(text, fields)

    return fields


def _extract_name_fields(text: str, fields: Dict[str, Any]) -> None:
    """Tenta extrair nome do beneficiário e pagador por proximidade de label."""
    lines = text.splitlines()

    for i, line in enumerate(lines):
        low = line.lower()

        if any(kw in low for kw in ("beneficiário", "beneficiario", "favorecido", "credor")):
            candidate = _next_nonempty(lines, i)
            if candidate and not any(c.isdigit() for c in candidate[:4]):
                fields.setdefault("beneficiario", candidate.strip())

        if any(kw in low for kw in ("pagador", "sacado", "devedor")):
            candidate = _next_nonempty(lines, i)
            if candidate and not any(c.isdigit() for c in candidate[:4]):
                fields.setdefault("pagador", candidate.strip())


def _next_nonempty(lines: List[str], start: int) -> Optional[str]:
    """Retorna a próxima linha não-vazia após o índice start (inclusive a própria se tiver conteúdo além do label)."""
    for line in lines[start + 1: start + 4]:
        stripped = line.strip()
        if stripped and len(stripped) > 3:
            return stripped
    return None


# ---------------------------------------------------------------------------
# Validações FEBRABAN
# ---------------------------------------------------------------------------

def _run_validations(fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executa as validações disponíveis com base nos campos extraídos.
    Retorna um dict com chave = nome da validação, valor = dict com
    'valido' (bool) e, se inválido, 'erro' (str).
    """
    validations: Dict[str, Any] = {}

    if "codigo_barras" in fields:
        ok, msg = validate_codigo_barras(str(fields["codigo_barras"]))
        validations["codigo_barras"] = {"valido": ok} if ok else {"valido": False, "erro": msg}

    if "linha_digitavel" in fields:
        ok, msg = validate_linha_digitavel(str(fields["linha_digitavel"]))
        validations["linha_digitavel"] = {"valido": ok} if ok else {"valido": False, "erro": msg}

    for key in ("cnpj_beneficiario", "cnpj_pagador"):
        if key in fields:
            ok, msg = validate_cnpj(str(fields[key]))
            validations[key] = {"valido": ok} if ok else {"valido": False, "erro": msg}

    return validations


# ---------------------------------------------------------------------------
# Cálculo de confiança
# ---------------------------------------------------------------------------

_HIGH_VALUE_FIELDS = {"linha_digitavel", "codigo_barras", "valor", "data_vencimento"}
_ALL_FIELDS = {
    "linha_digitavel", "codigo_barras", "valor", "data_vencimento", "data_emissao",
    "beneficiario", "cnpj_beneficiario", "pagador", "cpf_pagador", "cnpj_pagador",
    "nosso_numero", "agencia_conta", "banco",
}


def _compute_confidence(found: Dict[str, Any]) -> float:
    found_keys = set(found.keys())
    high = len(found_keys & _HIGH_VALUE_FIELDS) / len(_HIGH_VALUE_FIELDS)
    total = len(found_keys) / len(_ALL_FIELDS)
    return round(high * 0.7 + total * 0.3, 2)


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def decode_and_save_pdf(file_base64: str, filename: str) -> str:
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Apenas arquivos PDF são suportados (.pdf).")
    try:
        pdf_bytes = base64.b64decode(file_base64)
    except Exception:
        raise ValueError("O campo 'file_base64' não contém um Base64 válido.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        return tmp.name


def filter_fields(raw_fields: Dict[str, Any], requested: Optional[List[str]]) -> Dict[str, Any]:
    if not requested:
        return raw_fields
    return {k: v for k, v in raw_fields.items() if k in requested}


def run_extraction(
    file_base64: str,
    filename: str,
    document_type: str = "boleto",
    requested_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    tmp_path = decode_and_save_pdf(file_base64, filename)

    try:
        text, method = _get_text(tmp_path)
        logger.info("Texto extraído via '%s' (%d chars).", method, len(text))

        if document_type in ("boleto", "auto"):
            raw_fields = _extract_boleto_fields(text)
            doc_type = "boleto"
        else:
            raise ValueError(
                f"Tipo de documento '{document_type}' não suportado nesta versão. "
                "Use 'boleto' ou 'auto'."
            )
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    validations = _run_validations(raw_fields)
    filtered = filter_fields(raw_fields, requested_fields)
    confidence = _compute_confidence(raw_fields)

    return {
        "document_type": doc_type,
        "confidence": confidence,
        "fields": filtered,
        "validations": validations,
        "extraction_method": method,
    }


# ---------------------------------------------------------------------------
# LLM opcional
# ---------------------------------------------------------------------------

from .config import settings


def run_llm_analysis(fields: Dict[str, Any]) -> Optional[str]:
    if not settings.LLM_ENABLED:
        return None

    provider = (settings.LLM_PROVIDER or "").lower()
    prompt = settings.LLM_PROMPT or ""
    fields_text = "\n".join(f"{k}: {v}" for k, v in fields.items())
    user_message = f"{prompt}\n\nCampos extraídos:\n{fields_text}"

    try:
        if provider == "openai":
            return _llm_openai(user_message)
        elif provider == "anthropic":
            return _llm_anthropic(user_message)
        elif provider == "groq":
            return _llm_groq(user_message)
        else:
            logger.warning("LLM_PROVIDER '%s' não reconhecido.", provider)
            return None
    except Exception as exc:
        logger.error("Falha na análise LLM: %s", exc)
        return f"Erro na análise LLM: {exc}"


def _llm_openai(msg: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=settings.LLM_API_KEY)
    r = client.chat.completions.create(
        model=settings.LLM_MODEL or "gpt-4o-mini",
        messages=[{"role": "user", "content": msg}],
    )
    return r.choices[0].message.content


def _llm_anthropic(msg: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.LLM_API_KEY)
    m = client.messages.create(
        model=settings.LLM_MODEL or "claude-haiku-5-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": msg}],
    )
    return m.content[0].text


def _llm_groq(msg: str) -> str:
    from groq import Groq
    client = Groq(api_key=settings.LLM_API_KEY)
    r = client.chat.completions.create(
        model=settings.LLM_MODEL or "llama3-8b-8192",
        messages=[{"role": "user", "content": msg}],
    )
    return r.choices[0].message.content
