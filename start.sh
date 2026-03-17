#!/bin/sh
# ── NEXUS Startup Script ─────────────────────────────────────────────

echo "🔍 Buscando intérprete Python..."

# Método 1: Usar la ruta capturada durante el build
if [ -f ".python_path" ]; then
    RESOLVED=$(cat .python_path | tr -d '[:space:]')
    if [ -n "$RESOLVED" ] && [ -x "$RESOLVED" ]; then
        echo "✅ Python desde build path: $RESOLVED"
        export PYTHON_BIN="$RESOLVED"
    fi
fi

# Método 2: Buscar en rutas conocidas del nix store
if [ -z "$PYTHON_BIN" ]; then
    for DIR in /nix/store/*/bin; do
        for BIN in "$DIR/python3" "$DIR/python3.11" "$DIR/python3.10"; do
            if [ -x "$BIN" ]; then
                echo "✅ Python en nix store: $BIN"
                export PYTHON_BIN="$BIN"
                break 2
            fi
        done
    done
fi

# Método 3: PATH normal
if [ -z "$PYTHON_BIN" ]; then
    for NAME in python3 python3.11 python3.10 python; do
        BIN=$(command -v "$NAME" 2>/dev/null)
        if [ -n "$BIN" ]; then
            echo "✅ Python en PATH: $BIN"
            export PYTHON_BIN="$BIN"
            break
        fi
    done
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ CRÍTICO: No se encontró Python en ninguna ubicación."
    echo "   Build path: $(cat .python_path 2>/dev/null || echo 'no existe')"
    echo "   PATH actual: $PATH"
    exit 1
fi

echo "🚀 Iniciando NEXUS con Python: $PYTHON_BIN"
exec node index.js
