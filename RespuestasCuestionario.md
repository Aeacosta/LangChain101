# Respuestas

## Caso A Anthropic — ¿Multiagente o sobrearquitectura? 

1. Los sistemas multiagénticos son recomendados en aplicaciones donde la solución final se puede separar en varias tareas independientes. Siempre y cuando el costo en tokens no es una limitante considerable, el uso de arquitectura multiagéntica puede ser una buena alternativa.
2. Las tareas paralelizables son aquellas que no requieren información de otro agente. Esto no aplicaría para los casos donde es requerido compartir contexto o en sistemas asíncronos donde es crucial información de pasos previos.
3. Definiendo un rol detallado, un objetivo específico y definición de cuáles herramientas usar para cada agente, se reduce el riesgo de tareas redundantes entre ellos. Contextos independientes y tareas aisladas son también consideraciones importantes para evitar agentes redundantes.
4. El sistema recomienda usar 3 o más herramientas en paralelo. El consumo de tokens se puede basar en los datos donde se menciona 15 veces más respecto a un chat de IA habitual. El orquestador manda de 3 a 5 agentes a ejecutar en paralelo. Dada la limitante en agentes de su ventana de texto, el documento recomienda limitarlos a 200 000 tokens para evitar truncamientos. La expectativa del sistema es reducir los tiempos en un 90% con respecto a un sistema no agéntico.
5. ### Métricas de éxito para sistemas multiagénticos: <br>

    a. Completitud en respuestas. <br>
    b. Rango de repetibilidad. Qué tan frecuente el sistema agente da la misma respuesta sobre una misma pregunta. <br>
    c. Exactitud en las citas con respecto a la respuesta dada. <br>

    ### Métricas de degradación para sistemas multiagénticos

    a. Tasa de alucinaciones. <br>
    b. Incremento considerable en gasto de tokens. <br>
    c. Incremento en latencia de respuesta. <br>
6. Para casos de falla, realiza un reintento desde el punto guardado en memoria. Esto para que el orquestador no repita tareas ya completadas. Si un subagente tarda demasiado en su tarea, este puede comprometer al resto del sistema. Si bien el documento no menciona cómo manejar largas latencias, se puede recomendar un tiempo límite de proceso de tarea. Si este excede dicho tiempo, se considera un error del subagente.
7. Las siguientes variables son importantes a considerar para un plan de trazabilidad: <br>
     a. Consumo de tokens. <br>
     b. Herramientas usadas. <br>
     c. Prompt de entrada por subagente. <br>
     d. Respuesta de salida por subagente <br>
     e. Duración en respuesta. <br>
8. El sistema puede simplificarse a un solo agente si este es sencillo. Si la tarea es puntual y no requiere procesamiento intermedio ni coordinación entre etapas, puede hacer innecesario y costoso una arquitectura multiagéntica. Tampoco se recomienda sistemas multiagénticos en tareas lineales donde existen muchas dependencias secuenciales o casos donde los agentes requieren compartir el mismo contexto.
9. Primeramente, el grado de confianza es la principal métrica a la hora de analizar riesgos en sistemas. Aunque el sistema responda más rápido, si las respuestas son erróneas, no habrá beneficio alguno. En segundo lugar, se puede rescatar la latencia dado que un sistema multiagéntico tiene esta característica como su principal atractivo.
10. `No Go`: el sistema presenta una falta de intervención humana en evaluación de sus respuestas. Este solo depende de sus subagentes y orquestador. Es necesario incluir un protocolo de evaluación de calidad de respuesta.

[Fuente](https://www.anthropic.com/engineering/multi-agent-research-system?utm_source=chatgpt.c%20om)

## Caso B Uber Genie — El RAG responde, pero ¿es confiable? 

1. El mal desempeño de documentos: se utilizaban documentos en formato PDF o Markdown. Los cuales, a pesar de tener información confiable, al sistema RAG actual se le dificultaba interpretarlos por su formato. Ejemplo: tablas en markdown solían desalinearse entre filas y columnas.
2. Acceso a datos no autorizados: El LLM puede exponer datos sensibles de la compañía a usuarios. Información privada de usuarios puede caer en manos equivocadas afectando la reputación de la empresa. La alucinación puede dar información errónea a usuarios conllevando a problemas legales.
3. Se recomienda agregar al set de datos golden respuestas a preguntas comunes o ya existentes.
4. Se proponen las siguientes rúbricas de evaluación: <br>
    a. Tiempo en responder. <br>
    b. Completitud. <br>
    c. Veracidad. <br>
    d. Fidelidad a fuentes. <br>
    e. Satisfacción del usuario (sistema de me gusta / no me gusta o evaluación) <br>
5. Un Script puede evaluar métricas medibles como tiempo de respuesta o datos de usuarios. Veracidad en respuestas o evaluación de información sensible requerirá de intervención humana o un Juez LLM.
6. Para validación de un Juez LLM con respecto a los estándares SME, se propone comparar sus validaciones con el set de datos golden.
7. <br>
 ### Informativo

 Los datos generados por el sistema deben ser confiables y los rangos de alucinación o erróneas deberían estar debajo del 5%.

 ### Seguridad y Privacidad

 La exposición de información sensible, idealmente, tiene que ser nula. Dichos datos pueden comprometer los datos de la empresa y la información de sus usuarios.

 ### Política Interna

Dado este punto no es tan crucial ni sensible como los 2 previamente mencionados, este puede tener un umbral de calidad más flojo siempre y cuando no se incumplan las categorías previas. Si el 90% de las respuestas cumple con la política interna de la empresa, se podría considerar aceptable.<br>

8. A pesar de la considerable tasa de veracidad, la exposición a consejos erróneos o inseguros debe ser nula para un sistema tan delicado como el expuesto.
9. Un Dashboard puede incluir estadísticas de las diferentes calificaciones dadas por el LLM-as-a-judge. Gráficos mostrando en cuáles áreas el sistema RAG suele fallar más frecuentemente.
10. `Go With Conditions`: La mejora de la inyección por RAG dio resultados en la calidad de respuesta. Sin embargo, falta verificación en los datos e intervención humana en la evaluación de respuestas.

[Fuente](https://www.uber.com/us/en/blog/enhanced-agentic-rag/?utm_source=chatgpt.com)

## Caso C: Stripe — El agente recomienda, pero no decide 

1. Un agente puede consultar información, extraer datos de documentos adjuntos, hacer análisis preliminares de riesgo y generar borradores de respuestas a clientes sin algún daño significativo. Por otro lado, presentar informes de actividad sospechosa a autoridades legales no debe realizarse sin supervisión humana por la sensibilidad de estos. De igual forma, dejar a la IA interactuar con entidades ajenas a la empresa no puede realizarse a la ligera sin supervisión.
2. Una acción se puede clasificar según el tipo de acción a realizar.
3. Un revisor humano debe cerciorarse de si la respuesta dada es congruente, sigue los principios de la empresa y no toca temas sensibles. En caso de tratarse de temas sensibles, se tiene que respaldar con información confiable.
4. Si se requiere analizar una respuesta del sistema 6 meses posterior, es importante recolectar información como: versión, dado que la arquitectura pudo cambiar desde entonces, prompt de entrada, respuesta, prompt de salida y documentación con la que el modelo estaba alimentado.
5. La intervención humana debe ser la encargada de solucionar conflictos que el agente presente entre la información bibliográfica y las herramientas utilizadas, o bien un agente orquestador.
6. Al existir buenas métricas, el sistema puede diluir problemas encontrados con el riesgo de ser ignorados. Calificar los riesgos por nivel de severidad lograría que los accidentes sean resaltados sin importar el valor de la métrica general. Crear métricas donde los errores de alta severidad afectan más el indicador propuesto con respecto a faltas más leves.
7. Antes de tomar la decisión de automatizar una tarea, se debe corroborar con evaluación humana. Asignar tareas pequeñas a cada agente para poder ser validadas incrementalmente antes de su automatización.
8. Se establecen las siguientes métricas de <br>
    ### Negocio <br>
    a. Costo de tokens. <br>
    b. Tiempo de latencia. <br>
    c. Cantidad de revisiones humanas por día. <br>
    ### Calidad <br>
    a. Tiempo de respuesta. <br>
    b. Tasa de alucinaciones. <br>
    c. Tasa de modificación humana. <br>
    ### Riesgo <br>
    a. Casos de intento de inyección de prompts. <br>
    b. Alerta de aprobación a ciegas por error humano. <br> <br>
9. Para evitar revisiones por automatización o fatiga, se propone múltiples revisores sobre una misma respuesta para auditoría del primero. Establecer un flujo de trabajo que limite el exceso de revisiones diarias por humano aportaría a reducir este riesgo. Corroborar información con citas de la fuente utilizada.
10. `Go:` La intervención humana en etapas tempranas asegura fiabilidad en el sistema. En especial, al ser una empresa que trabaja con información sensible. Una vez que se concluye que el sistema esté estable, se procede a su automatización. Se presenta un plan de desarrollo confiable.

[Fuente](https://aws.amazon.com/blogs/machine-learning/production-grade-ai-agents-for-financial-compliance-lessons-from-stripe/)

## Evaluación Final

| Criterio | Peso | Evidencia de buen desempeño | Caso 1 | Caso 2 | Caso 3 |
|---|---|---|---|---|---|
| Calidad del diagnóstico | 25% | Distingue síntomas de causas; identifica riesgos y supuestos relevantes | 20% | 22%  | 24% |
| Decisiones justificadas | 20% | Recomienda arquitectura, autonomía y controles con trade-offs explícitos | 12% | 15% |  19% |
| Diseño de evaluación | 20% | Define métricas, dataset, umbrales y combinación sensata de evaluación automática y humana | 10% | 15% | 20% |
| Pensamiento de riesgo | 15% | Reconoce severidad, reversibilidad, privacidad, seguridad y responsabilidad | 9% | 14% | 14% |
| Viabilidad operativa | 10% | Considera costo, latencia, fallos de tools, monitoreo y mantenimiento | 8% | 6% | 8% |
| Comunicación y defensa | 10% | Presenta un dictamen claro, responde objeciones y usa evidencia del caso | 3% | 10% | 9% |
| **Total** | **100%** | | 62% | 82% | 94% |