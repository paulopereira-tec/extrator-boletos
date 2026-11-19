from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class ExtractRequest(BaseModel):
    file_base64: str = Field(
        ...,
        description="Conteúdo do arquivo PDF codificado em Base64."
    )
    filename: str = Field(
        default="document.pdf",
        description="Nome do arquivo. Deve terminar com .pdf."
    )
    document_type: str = Field(
        default="boleto",
        description=(
            "Tipo do documento. Atualmente suportado: 'boleto' e 'auto'. "
            "Com 'auto', o sistema tenta detectar como boleto."
        )
    )
    fields: Optional[List[str]] = Field(
        default=None,
        description=(
            "Lista de campos a retornar. Se não informado, retorna todos os campos encontrados. "
            "Campos disponíveis: linha_digitavel, codigo_barras, valor, data_vencimento, "
            "data_emissao, beneficiario, cnpj_beneficiario, pagador, cpf_pagador, "
            "cnpj_pagador, nosso_numero, agencia_conta, banco, banco_codigo."
        )
    )


class ValidationResult(BaseModel):
    valido: bool
    erro: Optional[str] = None


class ExtractResponse(BaseModel):
    document_type: str
    confidence: float = Field(description="Confiança da extração, de 0.0 a 1.0.")
    extraction_method: str = Field(
        description="Método usado na extração: 'native' (texto do PDF) ou 'ocr' (imagem)."
    )
    fields: Dict[str, Any]
    validations: Dict[str, ValidationResult] = Field(
        default_factory=dict,
        description=(
            "Resultado das validações FEBRABAN: "
            "codigo_barras, linha_digitavel, cnpj_beneficiario, cnpj_pagador."
        )
    )
    llm_analysis: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str
