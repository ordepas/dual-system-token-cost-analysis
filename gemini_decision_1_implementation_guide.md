# Guía de Implementación: Casos de Uso con Gemini Decision 1

Esta guía detalla paso a paso cómo configurar la API de **Gemini Decision 1** (`gemini-decision-1`) y utilizarla para implementar los 7 casos de uso avanzados del Sistema 1 en flujos de desarrollo y agentes autónomos (reemplazando arquitecturas previas como *Jev*).

---

## Fase 0: Instalación y Configuración

Para utilizar el endpoint especializado de decisiones de Google, asegúrate de utilizar el SDK oficial de Python `google-genai`.

### 1. Instalación de Dependencias
```bash
pip install google-genai
```

### 2. Configuración de Credenciales
Establece tu clave de API como una variable de entorno en tu sistema:
```bash
export GEMINI_API_KEY="tu-api-key-de-gemini"
```

### 3. Módulo Cliente Base (`decision_client.py`)
Crea un script auxiliar para estandarizar las llamadas al modelo en tu proyecto:

```python
import os
from google import genai
from google.genai import types

def evaluate_decisions(state_text: str, questions_dict: dict) -> dict:
    """
    Evalúa un estado de entrada contra un diccionario de preguntas tipadas usando Gemini Decision 1.
    """
    client = genai.Client()
    response = client.decisions.create(
        model="gemini-decision-1",
        state=state_text,
        questions=questions_dict,
    )
    
    results = {}
    for q_key, answer in response.answers.items():
        results[q_key] = {
            "value": getattr(answer, answer.type), # Extrae noul, choice o score automáticamente
            "confidence": answer.confidence
        }
    return results
```

---

## Casos de Uso Prácticos

### 1. Reemplazo del Método de Compresión de Contexto (*Compaction*)
* **Objetivo:** Evitar enviar todo el historial de chat a un modelo pesado para resumirlo; usar el Sistema 1 para evaluar qué mensajes y acuerdos son realmente relevantes.
* **Instrucción de implementación:**
  1. Configura un *hook* en tu agente que se active cuando la ventana de contexto supere un umbral crítico (ej. 25% de ocupación).
  2. Pasa el historial completo como `state` a `gemini-decision-1`.
  3. Define preguntas de tipo `noul` o `choice` para aislar acuerdos técnicos, decisiones de arquitectura y errores resueltos.
  4. Inyecta únicamente los elementos validados al contexto principal del agente.

### 2. Capa de Verificación de Pruebas en Documentación (*Testing Compliance Layer*)
* **Objetivo:** Garantizar que cada regla de control de acceso o especificación técnica definida en la documentación cuente con su prueba unitaria o de integración.
* **Instrucción de implementación:**
  1. Intercepta las ediciones de archivos de seguridad o control de acceso mediante un hook.
  2. Envía el contenido modificado y las reglas extraídas de `docs/` como `state`.
  3. Configura preguntas de tipo `noul` para verificar si cada regla específica posee cobertura de test.
  4. Si se detectan carencias, genera un reporte automático ordenando al agente escribir las pruebas faltantes.

### 3. Selector Inteligente de Habilidades (*Skill Picker*)
* **Objetivo:** Prevenir la sobrecarga de contexto eligiendo instantáneamente la única habilidad (*skill*) adecuada según el prompt del usuario.
* **Instrucción de implementación:**
  1. Lee dinámicamente los nombres y descripciones de las habilidades disponibles.
  2. Usa el prompt del usuario como `state` en `gemini-decision-1`.
  3. Configura una pregunta de tipo `choice` donde las opciones sean los identificadores de cada skill o "ninguna".
  4. Carga únicamente la habilidad seleccionada en el entorno activo del agente.

### 4. Búsqueda y Indexación Rápida de Archivos (*Fast File Explorer*)
* **Objetivo:** Reemplazar exploradores de archivos lentos por un filtrado y ranking rápido de candidatos utilizando decisiones tipadas.
* **Instrucción de implementación:**
  1. Realiza una búsqueda inicial por palabras clave para obtener una lista corta de archivos candidatos (ej. 30 archivos).
  2. Envía las rutas y fragmentos de cabecera como `state`.
  3. Utiliza preguntas de tipo `score` o `choice` para puntuar la relevancia de cada archivo de 0 a 1.
  4. Haz que el agente abra únicamente los 2 o 3 archivos mejor valorados.

### 5. Capa de Filtrado Pre-Revisión de Código (*Pre-Review Gatekeeper*)
* **Objetivo:** Agilizar las revisiones de código filtrando cambios triviales o seguros mediante el Sistema 1 antes de pasar a revisiones profundas.
* **Instrucción de implementación:**
  1. Captura el *diff* de los cambios realizados antes de realizar un commit o pull request.
  2. Envía el *diff* como `state` evaluando 7 preguntas binarias (`noul`) sobre estilo, seguridad y directrices.
  3. Si todas las respuestas indican conformidad con alta confianza, el agente aprueba automáticamente el cambio. De lo contrario, escala a revisión profunda.

### 6. Navegación Asistida para Pruebas de Interfaz (*Browser UI Navigation*)
* **Objetivo:** Guiar de forma autónoma a un agente de pruebas en navegador decidiendo en qué elemento interactivo hacer clic paso a paso.
* **Instrucción de implementación:**
  1. Extrae una instantánea textual o lista estructurada de botones, enlaces e inputs visibles en la pantalla actual.
  2. Envía dicha lista y el objetivo de la prueba como `state`.
  3. Configura una pregunta de tipo `choice` para que el modelo devuelva el selector exacto del elemento a accionar.
  4. Repite el bucle de manera iterativa hasta alcanzar el objetivo de la prueba.

### 7. Bloqueo de Cambios que Rompen Reglas (*Spec Enforcement Hook*)
* **Objetivo:** Impedir estrictamente que el agente aplique código que viole las especificaciones arquitectónicas del proyecto.
* **Instrucción de implementación:**
  1. Instala un hook previo a la escritura en disco (`pre-write hook`).
  2. Envía el bloque de código propuesto junto con las reglas del proyecto (`specs.md`) como `state`.
  3. Configura preguntas binarias (`noul`) para detectar infracciones a las directrices.
  4. Si el nivel de confianza de infracción supera el umbral configurado (ej. 80%), bloquea la operación y notifica el motivo de inmediato.