# 🚀 GUÍA DE INSTALACIÓN NEXUS v3 EN TERMUX

## 📱 PASO 1: Instalar dependencias en Termux

```bash
# Actualizar paquetes
pkg update && pkg upgrade -y

# Instalar Python y Node.js
pkg install python nodejs git -y

# Instalar compilador C (necesario para NumPy)
pkg install clang make -y

# Instalar dependencias de Python científicas
pkg install python-numpy -y

# O si prefieres compilar desde pip:
pip install --upgrade pip
pip install numpy

# Instalar dependencias de Node.js
npm install
```

## ⚠️ SOLUCIÓN AL ERROR DE NUMPY

El error que ves (`ModuleNotFoundError: No module named 'numpy'`) ocurre porque:

1. **NumPy no está instalado** en tu entorno de Python
2. **Estás usando Python del sistema** en lugar del de Termux

### Solución rápida:
```bash
# Opción 1: Instalar desde pkg (más rápido, recomendado para Termux)
pkg install python-numpy

# Opción 2: Instalar desde pip
pip install numpy --no-cache-dir

# Verificar instalación
python3 -c "import numpy; print(numpy.__version__)"
```

## 📦 PASO 2: Configurar variables de entorno

Crea un archivo `.env` en la raíz del proyecto:

```bash
# Motor de lenguaje (elige UNO)
# Opción 1: Groq (recomendado - rápido y gratuito)
GROQ_API_KEY=tu_api_key_aqui
GROQ_MODEL=llama-3.3-70b-versatile

# Opción 2: Ollama (local, pero pesado para móvil)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# Base de datos (opcional)
# MONGODB_URI=mongodb://localhost:27017
# MONGODB_DB_NAME=nexus

# Puerto
PORT=3000
```

### Cómo obtener API key de Groq (GRATIS):
1. Ve a https://console.groq.com
2. Crea una cuenta
3. Ve a "API Keys"
4. Crea una nueva key y cópiala
5. Pégala en el archivo `.env`

## 🧠 PASO 3: Iniciar el servidor

```bash
# Desde la carpeta del proyecto
cd nexus_v3

# Instalar dependencias de Node.js
npm install

# Iniciar servidor
node server.js
```

## 📱 PASO 4: Acceder desde el navegador

```bash
# En Termux, el servidor se ejecuta en:
http://localhost:3000

# O desde tu navegador móvil:
# Abre Chrome/Firefox y ve a: localhost:3000
```

## 🔧 SOLUCIÓN A PROBLEMAS COMUNES

### 1. Error "Brain cerró (code=1)"
```bash
# Instalar NumPy correctamente
pkg install python-numpy -y

# Verificar que Python encuentra NumPy
python3 -c "import numpy as np; print(np.__version__)"
```

### 2. Error "Cannot find module 'dotenv'"
```bash
npm install dotenv express cors axios cheerio mongodb
```

### 3. Puerto 3000 ocupado
```bash
# Cambiar puerto en .env
PORT=8080

# O matar proceso anterior
pkill -f "node server.js"
```

### 4. "LLM no conectado"
Tienes dos opciones:

**Opción A: Usar Groq (RECOMENDADO para móvil)**
```bash
# Agregar a .env
GROQ_API_KEY=tu_key_aqui
GROQ_MODEL=llama-3.3-70b-versatile
```

**Opción B: Usar Ollama (requiere más recursos)**
```bash
# Instalar Ollama en Termux (experimental)
pkg install ollama -y
ollama serve &
ollama pull llama3.2
```

## 📊 ARQUITECTURA DE NEXUS

```
nexus_v3/
├── server.js          # Servidor Express (Node.js)
├── neural/
│   ├── brain.py       # Cerebro principal + LLM
│   ├── network.py     # Redes neuronales (ranking + intent)
│   ├── embeddings.py  # Embeddings de n-gramas
│   └── memory.py      # Memoria (episódica + semántica + trabajo)
├── public/
│   └── index.html     # Interfaz web (ahora responsive!)
├── models/            # Pesos de las redes neuronales
├── data/              # Memoria persistente
└── .env               # Variables de entorno

FLUJO:
Usuario → index.html → server.js → brain.py → LLM (Groq/Ollama)
                          ↓
                    Redes neuronales
                    + Memoria
                    + Web search
```

## 🎨 MEJORAS IMPLEMENTADAS

### ✅ Diseño Responsive
- Menú hamburguesa para móviles
- Sidebar deslizable
- Texto adaptable
- Touch-friendly
- Safe area para iOS

### ✅ Soporte Groq
- API key en .env
- Modelos rápidos (70B)
- Gratis (límites generosos)
- Sin instalación local

### ✅ Fallback sin NumPy
- Si NumPy falla, usa listas Python
- Funciona (más lento) sin dependencias

## 🚀 CONSEJOS DE RENDIMIENTO

### Para Termux en móvil:
1. **Usa Groq en lugar de Ollama** (mucho más ligero)
2. **Cierra apps en segundo plano** para liberar RAM
3. **Usa modo de bajo consumo** si es posible
4. **No ejecutes entrenamientos masivos** en móvil

### Monitorear recursos:
```bash
# Ver uso de CPU/RAM
top

# Ver procesos Python
ps aux | grep python
```

## 🐛 DEBUG

Si algo no funciona:

```bash
# Ver logs del servidor
node server.js

# Ver logs de Python directamente
python3 neural/brain.py

# Verificar todas las dependencias
npm list
pip list | grep numpy
```

## 📞 CONTACTO

Si tienes problemas:
1. Verifica que NumPy esté instalado: `python3 -c "import numpy"`
2. Verifica que el .env tenga GROQ_API_KEY
3. Revisa los logs en la terminal

## 🎯 PRÓXIMOS PASOS

Una vez funcionando:
1. Experimenta con diferentes modelos de Groq
2. Ajusta la temperatura y parámetros en brain.py
3. Entrena las redes con tus conversaciones
4. Explora la memoria episódica y semántica

¡Disfruta de tu IA personal! 🧠✨
