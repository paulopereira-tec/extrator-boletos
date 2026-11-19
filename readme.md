# DocExtractor API

Microsserviço em Python/FastAPI para extração de dados de boletos bancários a partir de arquivos PDF.

A API aceita o PDF codificado em Base64, extrai o texto nativo ou usa OCR para PDFs escaneados e identifica campos como linha digitável, código de barras, valor, vencimento e dados do beneficiário/pagador.

## Recursos

- Extração de boletos bancários em texto nativo.
- OCR em português como fallback para PDFs escaneados.
- Validação dos campos conforme regras FEBRABAN.
- Filtro opcional dos campos retornados.
- Controle de ativação da extração em tempo de execução.
- Documentação interativa com Swagger UI.
- Análise opcional dos campos extraídos por OpenAI, Anthropic ou Groq.

## Tecnologias

- Python 3.12
- FastAPI e Uvicorn
- pdfplumber
- pdf2image e pytesseract
- Tesseract OCR com idioma português
- Docker e Docker Compose

## Início rápido com Docker

Crie o arquivo `.env` a partir do exemplo:

```bash
cp .env.example .env
```

Construa e inicie o serviço:

```bash
docker compose up -d --build
```

A API ficará disponível em:

- Local: `http://127.0.0.1:8000`
- Documentação Swagger: `http://127.0.0.1:8000/docs`
- Documentação ReDoc: `http://127.0.0.1:8000/redoc`

O Compose expõe a porta somente em `127.0.0.1`. Para acesso externo, utilize um proxy reverso ou ajuste a publicação da porta em `docker-compose.yml`.

Para acompanhar os logs:

```bash
docker compose logs -f extractor
```

Para parar o serviço:

```bash
docker compose down
```

## Execução local sem Docker

Requisitos:

- Python 3.12
- Tesseract OCR
- Pacote de idioma português do Tesseract
- Poppler

Instale as dependências:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Inicie o servidor:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Configuração

As principais variáveis podem ser definidas no arquivo `.env`:

| Variável | Padrão | Descrição |
|---|---:|---|
| `LLM_ENABLED` | `false` | Habilita a análise dos campos por LLM |
| `LLM_PROVIDER` | vazio | Provedor: `openai`, `anthropic` ou `groq` |
| `LLM_API_KEY` | vazio | Chave de API do provedor selecionado |
| `LLM_MODEL` | depende do provedor | Modelo a utilizar |
| `LLM_PROMPT` | prompt padrão | Instrução enviada ao modelo |
| `LOG_LEVEL` | `info` | Nível de log: `debug`, `info`, `warning`, `error` |
| `STATE_FILE` | `/tmp/api_state.flag` | Caminho do arquivo que conserva o estado ativo/inativo |

Exemplo com OpenAI:

```dotenv
LLM_ENABLED=true
LLM_PROVIDER=openai
LLM_API_KEY=sk-sua-chave
LLM_MODEL=gpt-4o-mini
LLM_PROMPT=Analise o boleto extraído e indique se há irregularidades:
LOG_LEVEL=info
```

No Docker Compose, o volume `extractor_state` persiste o estado em `/tmp`.

## Controle da API

Por padrão, o serviço inicia ativo.

### Consultar o status

```http
GET /health
```

Exemplo de resposta:

```json
{
  "status": "ok",
  "active": true,
  "llm_enabled": false
}
```

### Ativar a extração

```http
POST /control?start=1
```

### Desativar a extração

```http
POST /control?start=0
```

Com a API desativada, todas as chamadas para `POST /extract` retornam HTTP `503`. O endpoint `/control` continua disponível para reativar o serviço.

## Extrair dados de um boleto

### Endpoint

```http
POST /extract
Content-Type: application/json
```

### Corpo da requisição

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---:|---|
| `file_base64` | `string` | Sim | Conteúdo completo do PDF codificado em Base64 |
| `filename` | `string` | Não | Nome do arquivo; deve terminar em `.pdf` |
| `document_type` | `string` | Não | `boleto` ou `auto`; o padrão é `boleto` |
| `fields` | `array[string]` | Não | Lista dos campos desejados; se omitida, retorna todos os encontrados |

Exemplo mínimo:

```json
{
  "file_base64": "JVBERi0xLjQK...",
  "filename": "boleto.pdf",
  "document_type": "boleto"
}
```

Exemplo filtrando campos:

```json
{
  "file_base64": "JVBERi0xLjQK...",
  "filename": "boleto.pdf",
  "document_type": "auto",
  "fields": [
    "linha_digitavel",
    "codigo_barras",
    "valor",
    "data_vencimento"
  ]
}
```

### Campos disponíveis

- `linha_digitavel`
- `codigo_barras`
- `valor`
- `data_vencimento`
- `data_emissao`
- `beneficiario`
- `cnpj_beneficiario`
- `pagador`
- `cpf_pagador`
- `cnpj_pagador`
- `nosso_numero`
- `agencia_conta`
- `banco`
- `banco_codigo`

Datas são retornadas no formato `YYYY-MM-DD`, e `valor` é retornado como número decimal.

### Exemplo com cURL

O comando abaixo gera o conteúdo Base64 do PDF e envia a requisição:

```bash
PDF_BASE64=$(base64 -w 0 boleto.pdf)

curl -X POST "http://127.0.0.1:8000/extract" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg pdf "$PDF_BASE64" '{
    file_base64: $pdf,
    filename: "boleto.pdf",
    document_type: "boleto",
    fields: ["linha_digitavel", "codigo_barras", "valor", "data_vencimento"]
  }')"
```

No PowerShell:

```powershell
$bytes = [System.IO.File]::ReadAllBytes("boleto.pdf")
$base64 = [Convert]::ToBase64String($bytes)

$body = @{
  file_base64 = $base64
  filename = "boleto.pdf"
  document_type = "boleto"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/extract" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

### Exemplo de resposta

```json
{
  "document_type": "boleto",
  "confidence": 0.86,
  "extraction_method": "native",
  "fields": {
    "linha_digitavel": "00190.00009 00000.000000 00000.000000 0 00000000000000",
    "codigo_barras": "00190000000000000000000000000000000000000000",
    "valor": 125.5,
    "data_vencimento": "2026-12-10",
    "banco_codigo": "001",
    "banco": "Banco do Brasil"
  },
  "validations": {
    "codigo_barras": {
      "valido": true
    },
    "linha_digitavel": {
      "valido": true
    },
    "cnpj_beneficiario": {
      "valido": true
    }
  },
  "llm_analysis": null
}
```

## Significado da resposta

| Campo | Descrição |
|---|---|
| `document_type` | Tipo identificado: atualmente `boleto` |
| `confidence` | Grau de confiança da extração, entre `0.0` e `1.0` |
| `extraction_method` | `native` para texto nativo ou `ocr` para PDF escaneado |
| `fields` | Campos encontrados no documento |
| `validations` | Validações disponíveis de código de barras, linha digitável e CNPJ |
| `llm_analysis` | Texto da análise opcional por LLM; `null` quando desativada |

As validações podem conter:

```json
{
  "valido": false,
  "erro": "Código de barras deve ter 44 dígitos; encontrado 43."
}
```

## Códigos de erro

| Status | Quando ocorre |
|---|---|
| `400 Bad Request` | Nome de arquivo inválido, Base64 inválido, tipo de documento não suportado ou parâmetro `start` inválido |
| `500 Internal Server Error` | Falha inesperada durante o processamento do PDF |
| `503 Service Unavailable` | A extração foi desativada com `POST /control?start=0` |

Exemplo de resposta de erro:

```json
{
  "detail": "Apenas arquivos PDF são suportados. O filename deve terminar com '.pdf'."
}
```

## Limitações

- Nesta versão, `document_type` aceita somente `boleto` e `auto`.
- A qualidade da extração depende da legibilidade e da estrutura do PDF.
- PDFs escaneados exigem OCR disponível no ambiente.
- `llm_analysis` é opcional e depende de um provedor configurado e da respectiva chave de API.
- Não há autenticação integrada configurada nesta versão.

## Licença

Este projeto está licenciado sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE).