
## Agent Codigo Limpio

### Sub agentes

- Extraccion de Reporte: Lee el codigo a evaluar y genera el reporte en formato JSON.
- Correccion de Codigo: Genera el código limpio generado del reporte extraído

```mermaid
flowchart TD
A(Inicio) --> B[Leer Archivos]
B --> C{JSON Valido?}
C -->|No|B
C --> D[Extraer Reporte]
D --> E[Calificar Reporte]
D --> F[Escribir Archivo corregido]
E --> G
F --> G(Fin)
```

### Herramientas

- Leer Archivo
- Escribir Archivo
- Extraer Reporte


## Agente Para Pruebas Unitarias

### Sub Agentes

- Generador de Pruebas Unitarias
- Validación y Cobertura para Pruebas Unitarias

```mermaid
flowchart TD
A(Inicio) --> B[Leer Archivos]
B --> C{Archivo C# válido?}
C -->|No|B
C --> D[Generar pruebas unitarias]
D --> E{Archivo C# válido?}
E --> |No|D
E --> F[Generar Cobertura]
F --> G{Cobertura esperada?}
G --> |Si|H(Fin)
G --> |No|I[Agregar mas pruebas unitarias]
I --> G
```

### Herramientas

- Leer Archivo
- Escribir Archivo
- Compilar y ejecutar pruebas unitarias

## Agente Validador de Requirimientos

```mermaid
flowchart TD
A(Inicio) --> B[Leer Hoja de Requirimientos]
B --> C[Analizar cambios .diff]
C --> D[Generar resumen ejecutivos de cambios]
D --> E[Comparar requirimientos y resumen]
E --> F{Cumple los requerimientos?}
F --> |No|G[Informar al usuario]
F --> |Si|H(Fin)
G --> H
```

### Herramientas

- Leer Archivo
- Leer Tiquetes (GitHub, Jira)
- GitHub MCP

### Sub Agentes

- Evaludor de requirimientos