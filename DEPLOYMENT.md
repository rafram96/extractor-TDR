# Deployment en Servidor del Cliente

Instrucciones para ejecutar extractor-Bases_TDR en el servidor del cliente.

## 📍 Servidor del Cliente

**Especificaciones:**
- OS: Windows 11 Pro 10.0.26200
- CPU: Intel Core i9-14900K (24 cores)
- RAM: 64GB DDR5
- GPU: NVIDIA Quadro RTX 5000 16GB VRAM
- SSD: 3TB NVMe

**Servicios:**
- Docker
- Ollama (`http://localhost:11434`)
- n8n
- OpenWebUI
- Nginx Proxy Manager

**Modelos en Ollama:**
- `qwen2.5vl:7b` (segmentación motor-OCR)
- `qwen2.5:14b` (extracción TDR — ESTE MÓDULO)

## 🔄 Paso 1: Pullear Repositorio

En el servidor, en PowerShell o Git Bash:

```bash
cd D:\proyectos
git clone <URL_REPO_EXTRACTOR_BASES_TDR>
cd extractor-Bases_TDR
```

**Estructura esperada en servidor:**
```
D:\proyectos\
├── motor-OCR\                    (ya existe)
├── extractor-Bases_TDR\          (nuevo)
├── infoobras\
│   └── ocr_output\               (output motor-OCR)
└── ...
```

## 📦 Paso 2: Instalar Dependencias

En PowerShell del servidor:

```powershell
cd D:\proyectos\extractor-Bases_TDR

# Crear entorno virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements.txt
```

## ✅ Paso 3: Verificar Configuración

### Verificar motor-OCR
```powershell
Test-Path "C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR\subprocess_wrapper.py"
```

Si retorna `False`, el wrapper script será creado automáticamente en primera ejecución.

### Verificar Ollama
```powershell
curl http://localhost:11434/api/tags
```

Debe retornar modelo `qwen2.5:14b` disponible.

### Verificar ocr_output directory
```powershell
Test-Path "D:\proyectos\infoobras\ocr_output"
```

Si no existe, crearlo:
```powershell
New-Item -ItemType Directory -Path "D:\proyectos\infoobras\ocr_output" -Force
```

## 🚀 Paso 4: Ejecutar Extracción

### Opción A: Procesamiento Completo

```powershell
cd D:\proyectos\extractor-Bases_TDR

python run_tdr_extraction.py `
  --pdf "C:\Users\Holbi\Downloads\1. CP consultoria obras 1-2026-VIVIENDA_opt.pdf" `
  --output "data\BASES_TDR_CRITERIOS.xlsx" `
  --verbose
```

**Tiempo esperado:** 10-20 minutos (depende de tamaño PDF y velocidad Ollama)

### Opción B: Solo Texto (sin LLM)
```powershell
python run_tdr_extraction.py `
  --pdf "path\to\pdf.pdf" `
  --text-only
```

**Tiempo esperado:** 5-10 minutos (motor-OCR)

### Opción C: Solo Parse (sin LLM, si motor-OCR ya ejecutó)
```powershell
python run_tdr_extraction.py `
  --pdf "path\to\pdf.pdf" `
  --parse-only
```

**Tiempo esperado:** < 1 segundo

## 📊 Flujo de Ejecución

```
1. [1-3 min] Validación inicial
   ├─ Motor-OCR disponible?
   ├─ Ollama disponible?
   └─ ocr_output directory existe?

2. [5-10 min] Lectura PDF
   ├─ Intenta pdfplumber
   └─ Si falla → motor-OCR subprocess

3. [< 1 min] Procesamiento markdown
   └─ Parse *_texto_*.md → diccionario

4. [5-10 min] Extracción LLM (dos pasos)
   ├─ LLM Paso 1: Cargos
   └─ LLM Paso 2: Experiencias

5. [< 1 min] Generación Excel
   └─ 3 sheets con formato

TOTAL: 10-20 minutos
```

## 📁 Outputs

### Excel
```
D:\proyectos\extractor-Bases_TDR\data\BASES_TDR_CRITERIOS.xlsx
```

3 hojas:
1. **Criterios RTM Profesionales**
2. **Experiencias Solicitadas**
3. **Información** (metadatos)

### Texto (si --text-only)
```
D:\proyectos\extractor-Bases_TDR\data\{nombre_pdf}_texto.txt
```

### Motor-OCR temps
```
D:\proyectos\infoobras\ocr_output\{nombre_pdf}\
├── {nombre}_texto_*.md
├── {nombre}_metricas_*.md
└── pages\                  (si keep_images=True)
```

## 🔧 Troubleshooting en Servidor

### Motor-OCR falla
**Síntoma:** "motor-OCR falló con código X"

```powershell
# Verificar wrapper script
cat "C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR\subprocess_wrapper.py"

# Verificar ocr_output es accesible
Test-Path "D:\proyectos\infoobras\ocr_output" -PathType Container
```

### Ollama timeout
**Síntoma:** "LLM no respondió tras 3 intentos"

```powershell
# Verificar Ollama está activo
curl http://localhost:11434/api/tags

# Reiniciar Ollama si es necesario
# (puede estar usando mucha GPU por otro proceso)
```

### Poco texto extraído
**Síntoma:** "motor-OCR extrajo muy poco texto (< 500 chars)"

```powershell
# Verificar directorio output
Get-ChildItem "D:\proyectos\infoobras\ocr_output\" -Recurse | grep "_texto_"

# Revisar metricas
Get-ChildItem "D:\proyectos\infoobras\ocr_output\" -Recurse | grep "_metricas_"
```

## 🔄 Integración con InfoObras

Después de generar el Excel TDR, se usa como input para:

**Paso 4:** Evaluación RTM
- Compara cargos/experiencias de propuesta vs. requisitos TDR
- Genera evaluación con 22 criterios

**Paso 5:** Cálculo de días efectivos
- Suma días descontando COVID, paralizaciones, etc.

## 📝 Logs y Debugging

### Logs detallados
```powershell
python run_tdr_extraction.py --pdf "..." --output "..." --verbose
```

Genera logs en console:
```
[HH:MM:SS] [INFO] [módulo]: Mensaje
[HH:MM:SS] [WARNING] [módulo]: Advertencia
[HH:MM:SS] [ERROR] [módulo]: Error
```

### Debug mode (para desarrolladores)
Editar `run_tdr_extraction.py` y cambiar:
```python
if args.verbose:
    logging.getLogger().setLevel(logging.DEBUG)
```

a:
```python
logging.getLogger().setLevel(logging.DEBUG)
```

## ✨ Notas Finales

1. **Primera ejecución:** Puede tomar más tiempo (Ollama carga modelo en memoria)
2. **Sucesivas ejecuciones:** Más rápidas (modelo en cache)
3. **VRAM:** Asegurar que GPU no está saturada por otros procesos
4. **Ruta PDF:** Usar rutas absolutas, no relativas
5. **Directorio output:** Se crea automáticamente si no existe

## 🆘 Soporte

Si encuentra errores:
1. Ejecutar con `--verbose` para ver logs detallados
2. Revisar `PLAN_IMPLEMENTACION_TDR.md` para entender arquitectura
3. Revisar README.md para opciones CLI
4. Verificar servicios en servidor (Ollama, motor-OCR)
