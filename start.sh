#!/bin/sh
# ── NEXUS Startup Script ─────────────────────────────────────────────
# Resuelve el binario de Python en el entorno real de Railway/Nix
# y lo exporta ANTES de que Node arranque.

echo "🔍 Buscando intérprete Python..."

# Intentar cada candidato en orden
for BIN in python3 python3.11 python3.10 python3.9 python; do
    RESOLVED=$(command -v "$BIN" 2>/dev/null)
    if [ -n "$RESOLVED" ]; then
        echo "✅ Python encontrado: $RESOLVED"
        export PYTHON_BIN="$RESOLVED"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ CRÍTICO: No se encontró Python. Abortando."
    exit 1
fi

echo "🚀 Iniciando NEXUS con Python: $PYTHON_BIN"
exec node index.js
