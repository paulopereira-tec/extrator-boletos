import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .models import ExtractRequest, ExtractResponse, ErrorResponse
from .extractor import run_extraction, run_llm_analysis
from .config import settings
from .state import get_state, set_state, is_active

logging.basicConfig(level=settings.LOG_LEVEL.upper())
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DocExtractor API",
    description=(
        "API para extração de dados de documentos PDF brasileiros "
        "via docextractbr, com suporte opcional a análise por LLM."
    ),
    version="1.0.0",
)


# ── /health ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Utilitários"], summary="Status da API")
def health_check():
    """Retorna o status operacional e o estado atual (ativo/inativo)."""
    active = is_active()
    return {
        "status": "ok",
        "active": active,
        "llm_enabled": settings.LLM_ENABLED,
    }


# ── /control ─────────────────────────────────────────────────────────────────

@app.post(
    "/control",
    tags=["Utilitários"],
    summary="Ligar ou desligar a API",
    responses={400: {"model": ErrorResponse}},
)
def control(
    start: int = Query(
        ...,
        description="1 = ativa o endpoint de extração | 0 = desativa (retorna 503 nas chamadas de extração)",
        ge=0,
        le=1,
    )
):
    """
    Controla a disponibilidade do endpoint `/extract`.

    - **start=1** → API ativa (comportamento normal)
    - **start=0** → API desativada; `/extract` retornará HTTP 503
    """
    try:
        set_state(start)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "message": "API ativada com sucesso." if start == 1 else "API desativada com sucesso.",
        "active": bool(start),
    }


# ── /extract ─────────────────────────────────────────────────────────────────

@app.post(
    "/extract",
    response_model=ExtractResponse,
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    tags=["Extração"],
    summary="Extrair dados de um PDF em Base64",
)
def extract(payload: ExtractRequest):
    """
    Recebe um PDF em **Base64**, chama a API docextractbr para extração
    e, se configurado, enriquece o resultado com análise de um LLM.

    - **file_base64**: PDF codificado em Base64
    - **filename**: nome do arquivo (deve terminar em `.pdf`)
    - **document_type**: tipo do documento (`auto`, `boleto`, `nfe`, `cnh`, …)
    - **fields**: lista de campos a retornar (omita para retornar todos)

    > **Requer que a API esteja ativa** (`POST /control?start=1`).
    """
    if not is_active():
        raise HTTPException(
            status_code=503,
            detail="A API de extração está desativada. Envie POST /control?start=1 para reativá-la.",
        )

    if not payload.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Apenas arquivos PDF são suportados. O filename deve terminar com '.pdf'.",
        )

    try:
        result = run_extraction(
            file_base64=payload.file_base64,
            filename=payload.filename,
            document_type=payload.document_type,
            requested_fields=payload.fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Erro durante a extração.")
        raise HTTPException(status_code=500, detail=f"Erro interno na extração: {exc}")

    llm_analysis = run_llm_analysis(result["fields"])

    return ExtractResponse(
        document_type=result["document_type"],
        confidence=result["confidence"],
        extraction_method=result.get("extraction_method", "native"),
        fields=result["fields"],
        validations=result.get("validations", {}),
        llm_analysis=llm_analysis,
    )
