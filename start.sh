#!/bin/sh

echo "🔍 Cargando entorno Nix..."

# Cargar el perfil Nix para tener acceso a todos los paquetes instalados
[ -f /root/.nix-profile/etc/profile.d/nix.sh ] && . /root/.nix-profile/etc/profile.d/nix.sh
[ -f /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ] && . /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh

# Agregar rutas Nix al PATH manualmente por si acaso
export PATH="/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:$PATH"

echo "PATH: $PATH"

# Buscar Python
for NAME in python3 python3.11 python3.10 python; do
    BIN=$(command -v "$NAME" 2>/dev/null)
    if [ -n "$BIN" ]; then
        echo "✅ Python encontrado: $BIN"
        export PYTHON_BIN="$BIN"
        break
    fi
done

# Si aún no se encuentra, buscar en nix store directamente
if [ -z "$PYTHON_BIN" ]; then
    BIN=$(find /nix/store -name "python3" -type f 2>/dev/null | head -1)
    if [ -n "$BIN" ]; then
        echo "✅ Python en nix store: $BIN"
        export PYTHON_BIN="$BIN"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ No se encontró Python. PATH: $PATH"
    exit 1
fi

echo "🚀 Iniciando NEXUS: $PYTHON_BIN"
exec node index.js
