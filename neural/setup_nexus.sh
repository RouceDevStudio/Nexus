#!/bin/bash
# ═══════════════════════════════════════════════════════
#  NEXUS - Script de instalación/actualización
#  Ejecutar en Termux: bash setup_nexus.sh
# ═══════════════════════════════════════════════════════

echo ""
echo "🔧 Actualizando NEXUS..."
echo ""

NEURAL_DIR=~/nexus_/neural
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Instalar dependencias Python ────────────────────
echo "📦 Instalando dependencias Python..."

python3 -c "import pymongo; print('  ✓ pymongo:', pymongo.version)" 2>/dev/null || {
    pip install pymongo --break-system-packages -q && echo "  ✓ pymongo instalado" || echo "  ✗ Error pymongo"
}

python3 -c "import dns; print('  ✓ dnspython OK')" 2>/dev/null || {
    echo "  Instalando dnspython (necesario para MongoDB Atlas SRV)..."
    pip install dnspython --break-system-packages -q && echo "  ✓ dnspython instalado" || echo "  ✗ Error dnspython"
}

# ── 2. Verificar .env ──────────────────────────────────
echo ""
echo "🔍 Verificando .env..."

if grep -q "^MONGODB_URI=.\+" ~/nexus_/.env 2>/dev/null; then
    echo "  ✓ MONGODB_URI configurado"
else
    echo "  ⚠️  MONGODB_URI no encontrado"
    printf "  Pega tu URI de MongoDB Atlas (Enter para saltar): "
    read -r MONGO_INPUT
    if [ -n "$MONGO_INPUT" ]; then
        grep -v "^MONGODB_URI=" ~/nexus_/.env > /tmp/.env_tmp 2>/dev/null && mv /tmp/.env_tmp ~/nexus_/.env
        echo "MONGODB_URI=$MONGO_INPUT" >> ~/nexus_/.env
        echo "MONGODB_DB_NAME=nexus" >> ~/nexus_/.env
        echo "  ✓ URI guardado"
    fi
fi

# ── 3. Copiar archivos ─────────────────────────────────
echo ""
echo "🧠 Copiando archivos..."
for FILE in brain.py dynamic_params.py memory.py; do
    for SRC in "$SCRIPT_DIR/$FILE" ~/Downloads/$FILE /sdcard/Download/$FILE; do
        if [ -f "$SRC" ] && [ "$SRC" != "$NEURAL_DIR/$FILE" ]; then
            cp "$SRC" "$NEURAL_DIR/$FILE" && echo "  ✓ $FILE" && break
        fi
    done
done

# ── 4. Limpiar pickles corruptos ───────────────────────
echo ""
echo "🗑️  Verificando pickles..."
for PKL in ~/nexus_/data/episodic.pkl ~/nexus_/models/*.pkl; do
    [ -f "$PKL" ] && python3 -c "import pickle; pickle.load(open('$PKL','rb'))" 2>/dev/null || {
        [ -f "$PKL" ] && { echo "  ⚠️  Corrupto → borrando: $PKL"; rm "$PKL"; }
    }
done
echo "  ✓ OK"

# ── 5. Verificar sintaxis ──────────────────────────────
echo ""
echo "🔬 Sintaxis Python..."
python3 -m py_compile "$NEURAL_DIR/brain.py"  && echo "  ✓ brain.py" || echo "  ✗ brain.py ERROR"
python3 -m py_compile "$NEURAL_DIR/memory.py" && echo "  ✓ memory.py" || echo "  ✗ memory.py ERROR"

# ── 6. Test búsqueda + MongoDB ────────────────────────
echo ""
echo "🌐 Probando internet y MongoDB..."
python3 << 'PYEOF'
import urllib.request, json

# Test búsqueda
try:
    req = urllib.request.Request(
        'https://api.duckduckgo.com/?q=python&format=json&no_html=1&skip_disambig=1',
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read())
    print(f"  ✓ DDG: {len(data.get('RelatedTopics', []))} temas")
except Exception as e:
    print(f"  ⚠️  DDG: {e}")

# Test MongoDB
from pathlib import Path
mongo_uri = ''
env = Path.home() / 'nexus_' / '.env'
if env.exists():
    for line in env.read_text(errors='ignore').splitlines():
        if line.strip().startswith('MONGODB_URI=') and len(line.strip()) > 12:
            mongo_uri = line.strip()[12:]

if not mongo_uri:
    print("  → MongoDB: no configurado (ok)")
else:
    try:
        # Fix DNS Termux
        import dns.resolver as _r
        _res = _r.Resolver(configure=False)
        _res.nameservers = ['8.8.8.8', '8.8.4.4', '1.1.1.1']
        _r.default_resolver = _res
    except:
        pass
    try:
        from pymongo import MongoClient
        c = MongoClient(mongo_uri, serverSelectionTimeoutMS=8000)
        c.admin.command('ping')
        print("  ✅ MongoDB: CONECTADO")
        c.close()
    except Exception as e:
        print(f"  ✗ MongoDB: {type(e).__name__}: {str(e)[:80]}")
        print("  → Verifica: Atlas → Network Access → Allow 0.0.0.0/0")
PYEOF

echo ""
echo "══════════════════════════════════════════════"
echo "  Listo. Inicia con: cd ~/nexus_ && node server.js"
echo "══════════════════════════════════════════════"
