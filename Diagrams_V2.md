# Pipelines LangGraph — Diagramas Mermaid


## 1 · Pipeline del Reporter de Código Limpio
**Archivo:** `CleanCodeReporter/GraphAgent.py` · **Estado:** `GraphState` · **Entrada:** `CleanCodeReporter/GraphAgent.run()`

Analiza un archivo C# en busca de code smells con un bucle de reintento ante JSON inválido, luego ejecuta la calificación y el parcheado del archivo en paralelo antes de fusionar los resultados.

```mermaid
flowchart TD
    START([INICIO])
    read_file["<b>read_file</b><br/><small>Agente ReAct</small><br/><small>→ raw_response</small>"]
    validate_json{"<b>validate_json</b><br/><small>JsonFormatterAgent</small><br/><small>¿JSON válido?</small>"}
    extract_report["<b>extract_report</b><br/><small>Parser JSON</small><br/><small>→ report</small>"]
    score_report["<b>score_report</b><br/><small>ScorerAgent</small><br/><small>→ score_json</small>"]
    patch_file["<b>patch_file</b><br/><small>FilePatcher</small><br/><small>→ patched</small>"]
    merge["<b>merge</b><br/><small>fusiona score_json → report</small>"]
    END([FIN])

    START --> read_file
    read_file --> validate_json
    validate_json -- válido --> extract_report
    validate_json -- reintentar --> read_file
    extract_report --> score_report
    extract_report --> patch_file
    score_report --> merge
    patch_file --> merge
    merge --> END
```

---

## 2 · Pipeline de Análisis XTP
**Archivo:** `XTPAnalyser/AnalysisGraph.py` · **Estado:** `XTPAnalysisState` · **Entrada:** `XTPAnalyser/Main.py`

Compara dos programas XTP, analiza su matriz Bin2Bin, justifica cada discrepancia y extrae una tabla de justificación estructurada.

```mermaid
flowchart TD
    START([INICIO])
    generate_diff["<b>generate_diff</b><br/><small>XTPProgramDiffAgent</small><br/><small>→ response_xtp_diff</small>"]
    analize_bin2bin["<b>analize_bin2bin</b><br/><small>XTPBin2BinMatrixAgent</small><br/><small>→ response_bin2bin</small>"]
    justify_mismatches["<b>justify_mismatches</b><br/><small>XTPMismatchJustificationAgent</small><br/><small>→ justification_table</small>"]
    extract_justification_table["<b>extract_justification_table</b><br/><small>XTPTableExtractor</small><br/><small>→ mismatch_df_json</small>"]
    END([FIN])

    START --> generate_diff
    generate_diff --> analize_bin2bin
    analize_bin2bin --> justify_mismatches
    justify_mismatches --> extract_justification_table
    extract_justification_table --> END
```

---

## 3 · Pipeline de Generación XTP
**Archivo:** `XTPAnalyser/graph.py` · **Estado:** `XTPState` · **Entrada:** `XTPAnalyser/ProgramGeneration.py`

Genera dos programas XTP sintéticos y una matriz de correlación Bin2Bin, luego escribe los archivos resultantes en disco.

```mermaid
flowchart TD
    START([INICIO])
    generate["<b>generate</b><br/><small>XTPGeneratorAgent</small><br/><small>→ generator_output</small>"]
    deliver["<b>deliver</b><br/><small>XTPDeliveryAgent</small><br/><small>→ delivery_result</small>"]
    END([FIN])

    START --> generate
    generate --> deliver
    deliver --> END
```
