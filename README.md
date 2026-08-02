# Guía de Instalación de Ollama e Integración con LangChain (Llama 3.1)

---

## 🛠️ Paso 1: Instalar Ollama en tu Sistema

1. Descarga el instalador oficial desde [ollama.com](https://ollama.com).
2. Selecciona tu sistema operativo (**Windows**, **Mac** o **Linux**).
3. Ejecuta el archivo descargado y completa el asistente de instalación.
4. Confirma que esté activo buscando el ícono de la pequeña llama en la barra de tareas de tu sistema.

---

## 📥 Paso 2: Descargar el Modelo Llama 3.1

1. Abre una nueva terminal en tu sistema (Símbolo del Sistema, PowerShell o Terminal de Mac/Linux).
2. Ejecuta el comando para descargar la versión optimizada de 8 billones de parámetros:
   ```bash
   ollama run llama3.1:8b
   ```
3. Espera a que la barra de progreso llegue al 100% (el modelo pesa aproximadamente 4.7 GB).
4. Cuando termine, aparecerá un prompt con el símbolo `>>>`. Escribe algo para verificar que responde localmente.
5. Para salir de la consola del modelo, escribe `/bye` y presiona Enter.

---

## 📦 Paso 3: Configurar tu Entorno de Python

Abre la terminal dentro de la carpeta de tu proyecto (`prueba_langchain`), asegúrate de tener tu entorno virtual (`.venv`) activado e instala los paquetes oficiales y actualizados:

```bash
.\Activate.ps1
```

## 🚀 Paso 4: Ejecutar el Proyecto

Ejecuta el script desde tu terminal para comprobar que la comunicación con Ollama es exitosa:

```bash
python ejemplo.py
```

---

### ✅ Beneficios de esta Configuración:
* **Zero Dead-Ends:** Al no depender de la estructura rígida de `free-claude-code`, no experimentarás errores `404 Not Found` ni problemas de rutas duplicadas.
* **Sin autenticación:** Al ejecutarse localmente, se eliminan por completo los errores de cabeceras o tokens inválidos (`401 Unauthorized`).
* **Seguridad de Datos:** Las consultas se procesan de forma nativa en tu CPU/GPU sin enviar información a servidores de terceros.
