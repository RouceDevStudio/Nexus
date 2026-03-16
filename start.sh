#!/data/data/com.termux/files/usr/bin/bash

# ═══════════════════════════════════════════════════════════
# NEXUS v3 - Script de Inicio para Termux
# ═══════════════════════════════════════════════════════════

echo "🧠 Iniciando NEXUS v3..."
echo ""

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────
# Verificar dependencias
# ─────────────────────────────────────────────

check_command() {
    if command -v $1 &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 instalado"
        return 0
    else
        echo -e "${RED}✗${NC} $1 NO instalado"
        return 1
    fi
}

echo "📦 Verificando dependencias..."
echo ""

ALL_OK=true

if ! check_command python3; then
    echo -e "${YELLOW}Instala Python:${NC} pkg install python"
    ALL_OK=false
fi

if ! check_command node; then
    echo -e "${YELLOW}Instala Node.js:${NC} pkg install nodejs"
    ALL_OK=false
fi

# Verificar NumPy
echo -n "Verificando NumPy... "
if python3 -c "import numpy" 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
    echo -e "${YELLOW}Instala NumPy:${NC} pkg install python-numpy"
    echo -e "  o también:     pip install numpy"
    ALL_OK=false
fi

echo ""

if [ "$ALL_OK" = false ]; then
    echo -e "${RED}⚠ Faltan dependencias. Instálalas primero.${NC}"
    echo ""
    echo "Comandos rápidos:"
    echo "  pkg update && pkg upgrade -y"
    echo "  pkg install python nodejs python-numpy -y"
    echo "  npm install"
    echo ""
    exit 1
fi

# ─────────────────────────────────────────────
# Verificar .env
# ─────────────────────────────────────────────

if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ Archivo .env no encontrado${NC}"
    echo ""
    echo "Creando .env desde .env.example..."
    
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${GREEN}✓${NC} .env creado"
        echo ""
        echo -e "${YELLOW}⚠ IMPORTANTE:${NC} Edita .env y agrega tu GROQ_API_KEY"
        echo "  1. Ve a: https://console.groq.com"
        echo "  2. Crea cuenta gratis"
        echo "  3. Crea API Key"
        echo "  4. Pégala en el archivo .env"
        echo ""
        echo "Edita con: nano .env"
        echo ""
        read -p "Presiona Enter cuando hayas configurado .env..."
    else
        echo -e "${RED}✗${NC} .env.example no encontrado"
        echo "Creando .env básico..."
        cat > .env << 'EOF'
# Motor de lenguaje
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

# Puerto
PORT=3000
EOF
        echo -e "${GREEN}✓${NC} .env creado"
        echo ""
        echo -e "${YELLOW}⚠ EDITA .env y agrega tu GROQ_API_KEY${NC}"
        echo "Comando: nano .env"
        echo ""
        exit 1
    fi
fi

# Verificar si hay API key configurada
if grep -q "GROQ_API_KEY=$" .env || grep -q "GROQ_API_KEY= *$" .env; then
    echo -e "${YELLOW}⚠ GROQ_API_KEY no configurada en .env${NC}"
    echo "NEXUS funcionará en modo básico (sin LLM)"
    echo ""
    echo "Para usar Groq:"
    echo "  1. Edita .env: nano .env"
    echo "  2. Agrega tu API key de https://console.groq.com"
    echo ""
fi

# ─────────────────────────────────────────────
# Verificar node_modules
# ─────────────────────────────────────────────

if [ ! -d node_modules ]; then
    echo "📦 Instalando dependencias de Node.js..."
    npm install
    echo ""
fi

# ─────────────────────────────────────────────
# Crear directorios necesarios
# ─────────────────────────────────────────────

mkdir -p models data logs cache

# ─────────────────────────────────────────────
# Verificar puerto disponible
# ─────────────────────────────────────────────

PORT=$(grep "^PORT=" .env | cut -d'=' -f2 | tr -d ' ')
if [ -z "$PORT" ]; then
    PORT=3000
fi

# Verificar si el puerto está ocupado
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠ Puerto $PORT ocupado${NC}"
    echo "Matando proceso anterior..."
    pkill -f "node server.js" 2>/dev/null
    sleep 2
fi

# ─────────────────────────────────────────────
# Iniciar NEXUS
# ─────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}🧠 NEXUS v3 - IA Real${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Servidor: http://localhost:$PORT"
echo ""
echo "Características:"
echo "  • Redes neuronales con backpropagation"
echo "  • Memoria episódica y semántica"
echo "  • LLM integrado (Groq/Ollama)"
echo "  • Búsqueda web automática"
echo "  • Aprende de cada conversación"
echo ""
echo "Comandos:"
echo "  • Ctrl+C para detener"
echo "  • Ver logs en tiempo real"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Capturar Ctrl+C
trap 'echo ""; echo "👋 Deteniendo NEXUS..."; pkill -f "node server.js"; exit 0' INT

# Iniciar servidor
node server.js

# Si el script llega aquí, hubo un error
echo ""
echo -e "${RED}✗ NEXUS se detuvo inesperadamente${NC}"
echo ""
echo "Revisa los errores arriba."
echo "Si necesitas ayuda, verifica:"
echo "  1. Todas las dependencias están instaladas"
echo "  2. El archivo .env está configurado"
echo "  3. NumPy funciona: python3 -c 'import numpy'"
echo ""
