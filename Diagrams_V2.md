# Pipelines LangGraph — Diagramas Mermaid


## 1 · Pipeline del Reporter de Código Limpio
**Archivo:** `CleanCodeReporter/GraphAgent.py` · **Estado:** `GraphState` · **Entrada:** `CleanCodeReporter/GraphAgent.run()`

Analiza un archivo C# en busca de code smells con un bucle de reintento ante JSON inválido, luego ejecuta la calificación y el parcheado del archivo en paralelo antes de fusionar los resultados. Opcionalmente crea una PR de GitHub por cada hallazgo.

```mermaid
flowchart TD
    START([INICIO])
    read_file["<b>read_file</b><br/><small>Agent ReAct — ChatOpenAI</small><br/><small>tools: read_local_file · read_github_url · find_documents</small><br/><small>→ raw_response</small>"]
    validate_json{"<b>validate_json</b><br/><small>JsonFormatterAgent</small><br/><small>¿JSON válido?</small>"}
    extract_report["<b>extract_report</b><br/><small>Parser JSON</small><br/><small>→ report</small>"]
    score_report["<b>score_report</b><br/><small>ScorerAgent — ChatOpenAI</small><br/><small>→ score_json</small>"]
    patch_file["<b>patch_file</b><br/><small>FilePatcher</small><br/><small>→ patched · patch_diff · finding_patches</small>"]
    merge["<b>merge</b><br/><small>fusiona score_json + patch_data → report</small>"]
    create_pr["<b>create_pr</b><br/><small>GithubPRAgent</small><br/><small>→ pr_urls</small>"]
    END([FIN])

    START --> read_file
    read_file --> validate_json
    validate_json -- válido --> extract_report
    validate_json -- reintentar --> read_file
    extract_report --> score_report
    extract_report --> patch_file
    score_report --> merge
    patch_file --> merge
    merge -- repo detectado --> create_pr
    merge -- sin repo --> END
    create_pr --> END
```

### Inyección de Langfuse — CleanCodeReporter

```mermaid
flowchart TD
    A["GraphAgent.run(file_path)"]
    B["get_callback(session_id=file_path)\nLangfuseCallbackHandler.py"]
    C["trace_name_context('CleanCodeReviewer')\npropagates OTel trace_name via langfuse.propagate_attributes"]
    D["compiled_graph.invoke(state, config={'callbacks':[cb]})"]
    E["Cada ChatOpenAI / ScorerAgent / JsonFormatterAgent\nllama a get_callback() + trace_name_context() propio"]
    F["Langfuse UI\n(trazas agrupadas bajo 'CleanCodeReviewer')"]

    A --> B --> C --> D --> E --> F
```

### RAG — CleanCodeReporter

```mermaid
flowchart LR
    PDFs["📂 Documentos/\n(PDFs de buenas prácticas)"]
    PDF_PROC["PDFProcessor\nchunks por capítulo"]
    VS["ChromaDB\ncollection: default\nVectorStore"]
    TOOL["Tool: find_documents(query)\nagent_setup.py"]
    AGENT["Agent ReAct\n(read_file_node)"]
    RAG_REF["ragReference en cada finding\n(cita APA del top chunk)"]

    PDFs --> PDF_PROC --> VS
    AGENT -- "consulta smell name" --> TOOL --> VS
    VS -- "top chunk" --> TOOL --> RAG_REF
```

---

## 2 · Pipeline de Análisis XTP
**Archivo:** `XTPAnalyser/AnalysisGraph.py` · **Estado:** `XTPAnalysisState` · **Entrada:** `XTPAnalyser/Main.py`

Obtiene los dos programas XTP desde GitHub por commit SHA, analiza su diferencia y la matriz Bin2Bin, justifica cada discrepancia, extrae una tabla estructurada y la enriquece con referencias a Pull Requests.

```mermaid
flowchart TD
    START([INICIO])
    fetch_programs["<b>fetch_programs</b><br/><small>XTPGitCommitAgent — _fetch_file_at_sha</small><br/><small>→ program_a · program_b · diff</small>"]
    generate_diff["<b>generate_diff</b><br/><small>XTPProgramDiffAgent — ChatOpenAI + RAG XTP</small><br/><small>→ response_xtp_diff</small>"]
    analize_bin2bin["<b>analize_bin2bin</b><br/><small>XTPBin2BinMatrixAgent — ChatOpenAI + RAG XTP</small><br/><small>→ response_bin2bin</small>"]
    justify_mismatches["<b>justify_mismatches</b><br/><small>XTPMismatchJustificationAgent — ChatOpenAI</small><br/><small>→ justification_table</small>"]
    extract_table["<b>extract_justification_table</b><br/><small>XTPTableExtractor — regex/pandas</small><br/><small>→ mismatch_df_json</small>"]
    link_prs["<b>link_prs_to_justifications</b><br/><small>XTPPRLinkerAgent</small><br/><small>→ pr_links_json · pr_summary_md</small>"]
    END([FIN])

    START --> fetch_programs
    fetch_programs --> generate_diff
    generate_diff --> analize_bin2bin
    analize_bin2bin --> justify_mismatches
    justify_mismatches --> extract_table
    extract_table --> link_prs
    link_prs --> END
```

### XTPPRLinkerAgent — Detalle interno

```mermaid
flowchart TD
    LINKER["XTPPRLinkerAgent.link(df, sha_a, sha_b)"]
    DISC["XTPPRDiscoveryAgent\nPhase 1 — async"]
    MCP["GitHub MCP\nnpx @modelcontextprotocol/server-github\nlist_pull_requests(state=closed)"]
    CAT["PR Catalogue\nJSON array"]
    MATCH["XTPPRMatcherAgent\nPhase 2 — async por fila\n(sin tools — todo en prompt)"]
    ENRICH["DataFrame enriquecido\n+ pr_numbers · pr_titles · pr_links"]
    MD["pr_summary_md\nMarkdown con hipervínculos a PRs"]

    LINKER --> DISC
    DISC --> MCP --> CAT
    CAT --> MATCH
    MATCH --> ENRICH --> MD
```

### Inyección de Langfuse — XTP Analyser

```mermaid
flowchart TD
    A["build_analysis_graph()"]
    B["Monkey-patch compiled.invoke\n→ _invoke_with_langfuse"]
    C["get_callback(session_id='sha_a..sha_b')\nHashea session a trace_id MD5"]
    D["trace_name_context('XTPAnalyser')"]
    E["Cada sub-agente llama\nget_callback() + trace_name_context(NombreAgente)"]
    F["Langfuse UI\n(trazas bajo 'XTPAnalyser')"]

    A --> B --> C --> D --> E --> F
```

### RAG — XTP Analyser

```mermaid
flowchart LR
    MDs["📂 DocumentosXTP/\n(Markdown — manual XTP)"]
    MD_PROC["MarkdownProcessor\nchunks por sección"]
    VS["ChromaDB\ncollection: XTP_Manual\nXTPRagCore"]
    TOOL1["Tool: find_xtp_documents(query)\nXTPGeneratorAgent"]
    TOOL2["Tool: find_xtp_documents(query)\nXTPBin2BinMatrixAgent"]
    AGENT1["XTPGeneratorAgent ReAct"]
    AGENT2["XTPBin2BinMatrixAgent ReAct"]

    MDs --> MD_PROC --> VS
    AGENT1 -- "consulta sintaxis XTP / parámetros" --> TOOL1 --> VS
    AGENT2 -- "consulta límites / bins" --> TOOL2 --> VS
```

---

## 3 · Pipeline de Generación XTP
**Archivo:** `XTPAnalyser/graph.py` · **Estado:** `XTPState` · **Entrada:** `XTPAnalyser/ProgramGeneration.py`

Recibe un programa XTP de entrada, aplica un delta paramétrico aleatorio para generar el Programa B con su matriz Bin2Bin CSV, y escribe los archivos resultantes en disco.

```mermaid
flowchart TD
    START([INICIO])
    generate["<b>generate</b><br/><small>XTPGeneratorAgent — ReAct + RAG XTP</small><br/><small>tools: select_random_xtp_delta · generate_bin2bin_csv · find_xtp_documents</small><br/><small>→ generator_output</small>"]
    deliver["<b>deliver</b><br/><small>XTPDeliveryAgent</small><br/><small>→ Program_A.xtp · Program_B.xtp · Bin2Bin_Matrix.csv</small>"]
    END([FIN])

    START --> generate
    generate --> deliver
    deliver --> END
```

### Inyección de Langfuse — XTP Generation

```mermaid
flowchart TD
    A["build_graph()"]
    B["Monkey-patch compiled.invoke\n→ _invoke_with_langfuse"]
    C["get_callback()\nsin session_id"]
    D["trace_name_context('XTPAnalyser')"]
    E["XTPGeneratorAgent llama\nget_callback() + trace_name_context('XTPGeneratorAgent')"]
    F["Langfuse UI"]

    A --> B --> C --> D --> E --> F
```
