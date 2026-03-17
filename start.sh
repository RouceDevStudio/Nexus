#!/bin/bash
# Exponer python3 de Nix al PATH en runtime - Ruta ajustada para detectar Python 3.11 específicamente
export PATH="/nix/store/*python3-3.11*/bin:/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Verificación detallada de Python
echo "=== VERIFICACIÓN DE PYTHON ==="
PYTHON_LOCATION=$(which python3 2>/dev/null || echo 'NO ENCONTRADO')
echo "Python3 path: $PYTHON_LOCATION"
if [ "$PYTHON_LOCATION" != "NO ENCONTRADO" ]; then
  echo "Python3 version: $(python3 --version 2>&1)"
  echo "Pip path: $(which pip 2>/dev/null || echo 'NO ENCONTRADO')"
else
  echo "ERROR: Python3 no fue localizado en el PATH"
  exit 1
fi

# Instalar paquetes Node.js faltantes para evitar errores de dependencias
echo "=== INSTALACIÓN DE DEPENDENCIAS NODE.JS ==="
npm install multer sharp mammoth pdf-parse --legacy-peer-deps

# Iniciar la aplicación
echo "=== INICIANDO APLICACIÓN ==="
node index.js
