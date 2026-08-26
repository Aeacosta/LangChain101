# prueba_langchain — Guía de Arquitectura y Configuración

Este repositorio contiene dos sistemas agénticos construidos sobre **LangGraph + LangChain**:

| Sistema | Carpeta | Descripción |
|---|---|---|
| **CleanCodeReviewer** | `CleanCodeReporter/` | Analiza archivos C# en busca de code smells, los califica y abre Issues en GitHub solicitando las correcciones |
| **XTP Analyser** | `XTPAnalyser/` | Compara programas XTP, analiza matrices Bin2Bin y vincula discrepancias a PRs de GitHub |

---

## 🛠️ Instalación

### Paso 1 — Instalar Ollama (opcional, para uso local)

1. Descarga el instalador oficial desde [ollama.com](https://ollama.com).
2. Ejecuta el archivo descargado y completa el asistente de instalación.
3. Para descargar el modelo Llama 3.1 8B:
   ```bash
   ollama run llama3.1:8b
   ```

### Paso 2 — Configurar el entorno Python

Activa el entorno virtual e instala las dependencias:

```bash
.\Activate.ps1
pip install -r Requirements.txt
```

### Paso 3 — Variables de entorno

Copia `.env.example` a `.env` y rellena los valores:

```env
# LLM (DeepSeek por defecto)
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-...
LLM_API_BASE=https://api.deepseek.com/v1

# Langfuse (observabilidad — opcional)
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# GitHub (para abrir Issues de code-smell y consultar repositorios XTP)
GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
```

---

## 🏗️ Arquitectura

### CleanCodeReviewer

#### Grafo LangGraph

```mermaid
flowchart TD
    START([INICIO])
    read_file["<b>read_file</b><br/><small>Agent ReAct — ChatOpenAI</small><br/><small>tools: read_local_file · read_github_url · find_documents</small><br/><small>→ raw_response</small>"]
    validate_json{"<b>validate_json</b><br/><small>JsonFormatterAgent</small><br/><small>¿JSON válido?</small>"}
    extract_report["<b>extract_report</b><br/><small>Parser JSON</small><br/><small>→ report</small>"]
    score_report["<b>score_report</b><br/><small>ScorerAgent — ChatOpenAI</small><br/><small>→ score_json</small>"]
    patch_file["<b>patch_file</b><br/><small>FilePatcher</small><br/><small>→ patched · patch_diff · finding_patches</small>"]
    merge["<b>merge</b><br/><small>fusiona score_json + patch_data → report</small>"]
    create_issue["<b>create_issue</b><br/><small>GithubPRAgent — un Issue con todos los hallazgos</small><br/><small>→ pr_urls</small>"]
    END([FIN])

    START --> read_file
    read_file --> validate_json
    validate_json -- válido --> extract_report
    validate_json -- reintentar --> read_file
    extract_report --> score_report
    extract_report --> patch_file
    score_report --> merge
    patch_file --> merge
    merge -- repo detectado --> create_issue
    merge -- sin repo --> END
    create_issue --> END
```

**Archivos clave:**

| Archivo | Rol |
|---|---|
| [`CleanCodeReporter/GraphAgent.py`](CleanCodeReporter/GraphAgent.py) | Definición del grafo, todos los nodos y aristas |
| [`CleanCodeReporter/agent_setup.py`](CleanCodeReporter/agent_setup.py) | Instancia el Agent ReAct con sus tres tools |
| [`CleanCodeReporter/Agent.py`](CleanCodeReporter/Agent.py) | Clase `Agent` — envuelve el ReAct loop |
| [`Helpers/JsonFormatterAgent.py`](Helpers/JsonFormatterAgent.py) | LLM de un solo turno que convierte texto libre a JSON schema |
| [`Helpers/ScorerAgent.py`](Helpers/ScorerAgent.py) | LLM de un solo turno que calcula nota y justificación |
| [`Helpers/FilePatcher.py`](Helpers/FilePatcher.py) | Aplica unified diffs al archivo fuente |
| [`CleanCodeReporter/GithubPRAgent.py`](CleanCodeReporter/GithubPRAgent.py) | Abre un Issue en GitHub con todos los hallazgos y sus diffs propuestos |

#### Inyección de Langfuse

```mermaid
flowchart TD
    A["GraphAgent.run(file_path)"]
    B["get_callback(session_id=file_path)\nLangfuseCallbackHandler.py\n→ trace_id = MD5(file_path)"]
    C["trace_name_context('CleanCodeReviewer')\nlangfuse.propagate_attributes vía OTel"]
    D["compiled_graph.invoke(state, config={'callbacks':[cb]})"]
    E["ScorerAgent / JsonFormatterAgent\ncada uno llama get_callback() + trace_name_context() propio"]
    F["Langfuse UI\n(trazas bajo 'CleanCodeReviewer')"]

    A --> B --> C --> D --> E --> F
```

- **`get_callback(session_id)`** — retorna un `langfuse.langchain.CallbackHandler` sólo cuando las tres variables `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY` y `LANGFUSE_HOST` están definidas. Si falta alguna, retorna `None` y el sistema funciona sin observabilidad.
- **`trace_name_context(name)`** — context manager síncrono que llama `langfuse.propagate_attributes(trace_name=name)` para asignar el nombre a la traza activa en el UI de Langfuse (v4).

#### RAG — Documentos de buenas prácticas

```mermaid
flowchart LR
    PDFs["📂 Documentos/\n(PDFs — libros de código limpio)"]
    PDF_PROC["PDFProcessor\nchunks con título de capítulo"]
    VS["ChromaDB\ncollection: default\nVectorStore (cosine)"]
    TOOL["Tool: find_documents(query)\nagent_setup.py"]
    AGENT["Agent ReAct\n(read_file_node)"]
    RAG_REF["Campo ragReference\nen cada finding\n(cita APA del chunk más cercano)"]

    PDFs --> PDF_PROC --> VS
    AGENT -- "smell name como query" --> TOOL --> VS
    VS -- "top chunk" --> TOOL --> RAG_REF
```

- El agente llama `find_documents(query)` durante el análisis y copia la referencia APA retornada en el campo `ragReference` de cada finding.
- La colección es compartida (persistida en `.chroma/`) y se recarga al inicio.

---

### XTP Analyser

#### Pipeline de Análisis (`AnalysisGraph.py`)

```mermaid
flowchart TD
    START([INICIO])
    fetch_programs["<b>fetch_programs</b><br/><small>XTPGitCommitAgent — _fetch_file_at_sha</small><br/><small>Descarga program_a y program_b desde GitHub por SHA</small><br/><small>→ program_a · program_b · diff</small>"]
    generate_diff["<b>generate_diff</b><br/><small>XTPProgramDiffAgent — ChatOpenAI + RAG XTP</small><br/><small>→ response_xtp_diff</small>"]
    analize_bin2bin["<b>analize_bin2bin</b><br/><small>XTPBin2BinMatrixAgent — ChatOpenAI + RAG XTP</small><br/><small>→ response_bin2bin</small>"]
    justify_mismatches["<b>justify_mismatches</b><br/><small>XTPMismatchJustificationAgent — ChatOpenAI</small><br/><small>→ justification_table</small>"]
    extract_table["<b>extract_justification_table</b><br/><small>XTPTableExtractor — regex + pandas</small><br/><small>→ mismatch_df_json</small>"]
    link_prs["<b>link_prs_to_justifications</b><br/><small>XTPPRLinkerAgent — GitHub MCP + ChatOpenAI</small><br/><small>→ pr_links_json · pr_summary_md</small>"]
    END([FIN])

    START --> fetch_programs
    fetch_programs --> generate_diff
    generate_diff --> analize_bin2bin
    analize_bin2bin --> justify_mismatches
    justify_mismatches --> extract_table
    extract_table --> link_prs
    link_prs --> END
```

#### Pipeline de Generación (`graph.py`)

```mermaid
flowchart TD
    START([INICIO])
    generate["<b>generate</b><br/><small>XTPGeneratorAgent — ReAct + RAG XTP</small><br/><small>tools: select_random_xtp_delta · generate_bin2bin_csv · find_xtp_documents</small><br/><small>Aplica un delta paramétrico al Input Program → Program B + CSV</small><br/><small>→ generator_output</small>"]
    deliver["<b>deliver</b><br/><small>XTPDeliveryAgent</small><br/><small>Escribe Program_A.xtp · Program_B.xtp · Bin2Bin_Matrix.csv en disco</small><br/><small>→ delivery_result</small>"]
    END([FIN])

    START --> generate
    generate --> deliver
    deliver --> END
```

#### XTPPRLinkerAgent — Detalle interno

```mermaid
flowchart TD
    LINKER["XTPPRLinkerAgent.link(df, sha_a, sha_b)\nSíncrono — ejecuta event loop propio"]
    DISC["XTPPRDiscoveryAgent\nPhase 1 — async ainvoke"]
    MCP["GitHub MCP\nnpx @modelcontextprotocol/server-github\nlist_pull_requests(state=closed)"]
    CAT["PR Catalogue\nJSON array filtrado al rango sha_a..sha_b"]
    MATCH["XTPPRMatcherAgent\nPhase 2 — async por fila\nsin tools: catálogo en el prompt"]
    ENRICH["DataFrame enriquecido\n+ pr_numbers · pr_titles · pr_links"]
    MD["pr_summary_md\nMarkdown con hipervínculos a cada PR"]

    LINKER --> DISC
    DISC --> MCP --> CAT
    CAT --> MATCH
    MATCH --> ENRICH --> MD
```

**Archivos clave:**

| Archivo | Rol |
|---|---|
| [`XTPAnalyser/AnalysisGraph.py`](XTPAnalyser/AnalysisGraph.py) | Grafo de 6 nodos — análisis completo desde SHA hasta tabla con PRs |
| [`XTPAnalyser/graph.py`](XTPAnalyser/graph.py) | Grafo de 2 nodos — generación de programas XTP sintéticos |
| [`XTPAnalyser/Agents/XTPGitCommitAgent.py`](XTPAnalyser/Agents/XTPGitCommitAgent.py) | Descarga archivos XTP de GitHub por commit SHA |
| [`XTPAnalyser/Agents/XTPProgramDiffAgent.py`](XTPAnalyser/Agents/XTPProgramDiffAgent.py) | Analiza el diff entre dos programas XTP |
| [`XTPAnalyser/Agents/XTPBin2BinMatrixAgent.py`](XTPAnalyser/Agents/XTPBin2BinMatrixAgent.py) | Analiza la matriz de transición Bin2Bin |
| [`XTPAnalyser/Agents/XTPMismatchJustificationAgent.py`](XTPAnalyser/Agents/XTPMismatchJustificationAgent.py) | Justifica cada discrepancia con física de silicio |
| [`XTPAnalyser/Agents/XTPTableExtractor.py`](XTPAnalyser/Agents/XTPTableExtractor.py) | Extrae la tabla Markdown a un DataFrame pandas |
| [`XTPAnalyser/Agents/XTPPRLinkerAgent.py`](XTPAnalyser/Agents/XTPPRLinkerAgent.py) | Vincula discrepancias a PRs vía GitHub MCP |
| [`XTPAnalyser/Agents/XTPGeneratorAgent.py`](XTPAnalyser/Agents/XTPGeneratorAgent.py) | Genera Program B + matriz Bin2Bin con delta paramétrico |
| [`XTPAnalyser/Agents/XTPDeliveryAgent.py`](XTPAnalyser/Agents/XTPDeliveryAgent.py) | Escribe los archivos .xtp y .csv en disco |

#### Inyección de Langfuse — XTP

```mermaid
flowchart TD
    A["build_analysis_graph() / build_graph()"]
    B["Monkey-patch de compiled.invoke\n→ _invoke_with_langfuse"]
    C["get_callback(session_id='sha_a..sha_b')\ntrace_id = MD5(session_id)"]
    D["trace_name_context('XTPAnalyser')\npropagates OTel trace_name"]
    E["Cada sub-agente llama\nget_callback() + trace_name_context('NombreAgente')"]
    F["Langfuse UI\n(trazas bajo 'XTPAnalyser')"]

    A --> B --> C --> D --> E --> F
```

La integración de Langfuse se realiza en **dos niveles**:

1. **Nivel de grafo** — `build_analysis_graph()` reemplaza `compiled.invoke` con una versión que adjunta automáticamente el callback y establece el nombre de traza, sin requerir ningún cambio en el código que invoca el grafo.
2. **Nivel de sub-agente** — cada agente interno (`XTPBin2BinMatrixAgent`, `XTPGeneratorAgent`, etc.) llama a `get_callback()` y usa `trace_name_context()` con su propio nombre para que cada llamada LLM aparezca como span hijo en la traza de Langfuse.

#### RAG — Manual XTP

```mermaid
flowchart LR
    MDs["📂 DocumentosXTP/\n(Markdown — manual XTP)"]
    MD_PROC["MarkdownProcessor\nchunks por encabezado/sección"]
    VS["ChromaDB\ncollection: XTP_Manual\nXTPRagCore"]
    TOOL1["find_xtp_documents(query)\nXTPGeneratorAgent"]
    TOOL2["find_xtp_documents(query)\nXTPBin2BinMatrixAgent"]

    MDs --> MD_PROC --> VS
    VS -- "top-k chunks" --> TOOL1
    VS -- "top-k chunks" --> TOOL2
```

- **`XTPRagCore`** (`RAG/xtp_rag.py`) usa `MarkdownProcessor` para indexar los manuales en Markdown de `DocumentosXTP/` en una colección ChromaDB independiente (`XTP_Manual`), separada de la colección de buenas prácticas del CleanCodeReviewer.
- Tanto `XTPGeneratorAgent` como `XTPBin2BinMatrixAgent` exponen la misma tool `find_xtp_documents` que consulta esta colección antes de razonar sobre sintaxis XTP, límites paramétricos o tablas de binning.

---

## 📁 Estructura del Proyecto

```
prueba_langchain/
├── CleanCodeReporter/
│   ├── GraphAgent.py          # Grafo LangGraph — 7 nodos
│   ├── Agent.py               # Clase Agent — ReAct loop
│   ├── agent_setup.py         # Herramientas del agente + prompt
│   ├── GithubPRAgent.py       # Apertura de Issues en GitHub con hallazgos
│   ├── Rag.py                 # RagCore — PDFs de buenas prácticas
│   └── dash_app.py            # UI Dash
├── XTPAnalyser/
│   ├── AnalysisGraph.py       # Grafo de análisis — 6 nodos
│   ├── graph.py               # Grafo de generación — 2 nodos
│   ├── Main.py                # Punto de entrada — análisis
│   ├── ProgramGeneration.py   # Punto de entrada — generación
│   └── Agents/
│       ├── XTPGitCommitAgent.py
│       ├── XTPProgramDiffAgent.py
│       ├── XTPBin2BinMatrixAgent.py
│       ├── XTPMismatchJustificationAgent.py
│       ├── XTPTableExtractor.py
│       ├── XTPPRLinkerAgent.py
│       ├── XTPGeneratorAgent.py
│       └── XTPDeliveryAgent.py
├── Helpers/
│   ├── LangfuseCallbackHandler.py   # get_callback() + trace_name_context()
│   ├── JsonFormatterAgent.py        # Reformateador LLM → JSON schema
│   ├── ScorerAgent.py               # Motor de calificación LLM
│   ├── FilePatcher.py               # Aplicación de unified diffs
│   └── Logger.py
├── RAG/
│   ├── rag_config.py          # Configuración de carpeta y colección
│   ├── pdf_processor.py       # Chunking de PDFs
│   ├── markdown_processor.py  # Chunking de Markdown
│   ├── vector_store.py        # ChromaDB wrapper
│   └── xtp_rag.py             # XTPRagCore — colección XTP_Manual
├── Documentos/                # PDFs de libros de código limpio
├── DocumentosXTP/             # Manuales XTP en Markdown
├── Programas/                 # Archivos XTP generados (.xtp, .csv)
├── Estructuras/               # TypedDicts y schemas JSON
├── Diagrams_V2.md             # Diagramas Mermaid detallados
└── .env.example               # Plantilla de variables de entorno
```

---

## 🚀 Ejecución

### CleanCodeReviewer

```bash
python -m CleanCodeReporter.GraphAgent  # análisis de un archivo C#
python CleanCodeReporter/dash_app.py    # interfaz Dash en http://localhost:8050
```

### XTP Analyser — Generación

```bash
python XTPAnalyser/ProgramGeneration.py
```

### XTP Analyser — Análisis

```bash
python XTPAnalyser/Main.py
```

---

## ✅ Beneficios de la Configuración

- **Observabilidad granular:** Cada llamada LLM aparece como span hijo en Langfuse, agrupada por pipeline y sub-agente.
- **RAG desacoplado:** El CleanCodeReviewer y el XTP Analyser usan colecciones ChromaDB completamente independientes.
- **Langfuse opcional:** Si las variables `LANGFUSE_*` no están definidas, `get_callback()` retorna `None` y todos los pipelines funcionan sin modificaciones.
- **Sin dependencia de infraestructura remota para LLM:** Se puede apuntar a cualquier endpoint OpenAI-compatible vía `LLM_API_BASE`.
