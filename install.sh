#!/data/data/com.termux/files/usr/bin/bash
#
# NEXUS v5.0 ENHANCED - Script de Instalación
# Autor: Jhonatan David Castro Galvis
#

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  🧠 NEXUS AI v5.0 ENHANCED - Instalador                 ║"  
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Actualizar
echo "📦 Actualizando Termux..."
pkg update -y && pkg upgrade -y

# Instalar sistema
echo "📦 Instalando dependencias del sistema..."
pkg install -y python python-pip python-numpy nodejs git

# Instalar Python
echo "🐍 Instalando dependencias Python..."
pip install --upgrade pip --break-system-packages
pip install pymongo dnspython requests --break-system-packages

# Instalar Node.js
echo "📦 Instalando dependencias Node.js..."
npm install

# Crear directorios
echo "📁 Creando estructura..."
mkdir -p neural models data cache public

# Verificar
echo ""
echo "✅ Verificando instalación..."
python3 --version
node --version
npm --version
python3 -c "import numpy; print('NumPy:', numpy.__version__)"

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  ✅ INSTALACIÓN COMPLETADA                               ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "Próximos pasos:"
echo "1. Copia brain.py a neural/brain.py"
echo "2. Copia tus archivos de soporte (network.py, embeddings.py, etc.)"
echo "3. Ejecuta: npm start"
echo ""

