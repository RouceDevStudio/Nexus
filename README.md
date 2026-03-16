# 🧠 NEXUS v12.0 APEX — Neural Intelligence System

**Creado por:** Jhonatan David Castro Galviz  
**Propósito:** Sistema de asistencia inteligente para UpGames  
**Stack:** Node.js (API) + Python (Brain) + MongoDB Atlas

---

## ⚡ Arquitectura

```
index.js          → Servidor Express, auth, pagos, rutas API
neural/
  brain_vip.py    → Cerebro principal (NexusBrain) — proceso Python independiente
  brain.py        → Versión alternativa del brain
  groq_client.py  → Cliente unificado: Claude (Anthropic) → Groq → Ollama
  code_verifier.py→ 5 redes neurales de verificación de código
  memory.py       → WorkingMemory + EpisodicMemory + SemanticMemory
  embeddings.py   → EmbeddingMatrix (n-gramas)
  network.py      → NeuralNet base
  dynamic_params.py → DynamicNeuralNet auto-expansible
public/
  index.html      → Frontend principal (PWA)
  style.css       → Estilos
```

### Redes Neuronales Activas (11 total)

**8 Redes Cognitivas** (todas reciben estado PAD-3D como contexto emocional):
- RankNet, IntentNet, ContextNet, SentimentNet
- MetaNet, RelevanceNet, DialogueNet, QualityNet

**3 Redes Emocionales** (PersonalityEngine v3.0):
- `_AffectNet` — [26→64→32→16→3] auto-expansible, Adam optimizer
- `_EmotionContextNet` — aprende inercias del historial PAD
- `_EmotionRegulationNet` — modera estados extremos

### LLM — Jerarquía de proveedores
```
Claude (Anthropic) → Groq → Ollama → Smart Mode
```
Configurable con `LLM_PREFER` en `.env`.

---

## 📦 Instalación

### Requisitos
- Node.js >= 18
- Python >= 3.9
- MongoDB Atlas (URI en `.env`)

### Pasos

```bash
# 1. Instalar dependencias Node
npm install

# 2. Instalar dependencias Python
pip install -r requirements.txt
# En Termux:
pip install -r requirements.txt --break-system-packages

# 3. Configurar variables de entorno
cp Nexus.env.txt .env
# Editar .env con tus claves reales

# 4. Arrancar
npm start
```

Abre: `http://localhost:3000`

---

## 🔧 Variables de entorno (.env)

```env
# Base de datos
MONGODB_URI=mongodb+srv://...
MONGODB_DB_NAME=nexus

# Auth
JWT_SECRET=tu_secreto_jwt

# LLM (al menos uno)
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
OLLAMA_BASE_URL=http://localhost:11434   # opcional, local

# LLM preferido (opcional, default: claude)
LLM_PREFER=claude   # claude | groq | ollama

# Creador — emails con acceso VIP permanente y modo creator
CREATOR_EMAILS=email1@ejemplo.com,email2@ejemplo.com

# Render (se inyecta automáticamente en producción)
PORT=3000
RENDER_EXTERNAL_URL=https://tu-app.onrender.com
```

---

## 💰 Sistema de Planes

| Plan    | Mensajes/día | Generaciones/día | CodeGen | Precio |
|---------|-------------|-----------------|---------|--------|
| Free    | 10          | 5               | Básico  | Gratis |
| Premium | Ilimitado   | Ilimitado        | Completo| $10/mes|
| VIP     | Ilimitado   | Ilimitado        | Completo| Permanente |

Los contadores de generaciones se persisten en **MongoDB** (colección `daily_usage`) — sobreviven reinicios del servidor.

---

## 🚀 Deploy en Render

1. Conectar el repositorio en [render.com](https://render.com)
2. Tipo: **Web Service**
3. Build command: `npm install && pip install -r requirements.txt`
4. Start command: `npm start`
5. Agregar variables de entorno en el dashboard de Render

---

## 📁 Datos persistidos

| Archivo / Colección MongoDB | Contenido |
|----------------------------|-----------|
| `models/*.pkl`             | Pesos de las 8 redes cognitivas |
| `data/personality_v3.json` | Estado PAD + pesos de redes emocionales |
| `data/episodic.pkl`        | Memoria episódica (hasta 500k episodios) |
| `data/semantic.json`       | Hechos semánticos aprendidos |
| `data/conversations.json`  | Patrones de conversación |
| MongoDB `users`            | Cuentas, planes, contadores diarios |
| MongoDB `messages`         | Historial de mensajes (para límite diario) |
| MongoDB `daily_usage`      | Contadores de generaciones por usuario/día |
| MongoDB `payments`         | Historial de pagos |

---

*NEXUS v12.0 APEX — 11 redes activas · PAD-3D · Auto-expansible · Multi-LLM*
