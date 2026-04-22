/**
 * ══════════════════════════════════════════════════════════════════
 *  NEXUS ↔ UpGames — Rutas de integración profunda
 *  Archivo: rutas/nexusUpgames.js
 *
 *  Añade al index.js de Nexus:
 *    const { registerNexusUpgamesRoutes } = require('./rutas/nexusUpgames');
 *    registerNexusUpgamesRoutes(app, { brainVip, db, requireAuth, verificarAdmin,
 *                                      fetchUpGamesUserStats, buildBehavioralNarrative,
 *                                      UPGAMES_API_BASE, axios });
 *
 *  Endpoints expuestos:
 *    POST  /api/nexus/creator-mentor        → Analiza juego antes de publicar
 *    POST  /api/nexus/fraud-analyze         → Score de riesgo de fraude con IA
 *    GET   /api/nexus/creator-analytics/:u  → Insights predictivos del creador
 * ══════════════════════════════════════════════════════════════════
 */

'use strict';

function registerNexusUpgamesRoutes(app, deps) {
    const {
        brainVip,
        db,
        requireAuth,
        fetchUpGamesUserStats,
        buildBehavioralNarrative,
        UPGAMES_API_BASE,
        axios,
        isCreatorAccount,
        JWT_SECRET,
        jwt,
    } = deps;

    /**
     * Middleware: solo el creador (admin de Nexus) puede acceder.
     * En Nexus no existe panel de admin separado — el creador es el superusuario.
     */
    function requireCreator(req, res, next) {
        if (!req.user) return res.status(401).json({ error: 'No autenticado' });
        if (!req.user.isCreator && !isCreatorAccount(req.user.email)) {
            return res.status(403).json({ error: 'Acceso restringido al creador' });
        }
        next();
    }

    // ────────────────────────────────────────────────────────────────
    // Helpers internos
    // ────────────────────────────────────────────────────────────────

    /** Espera a que el brain esté listo; rechaza si no arranca en 10 s */
    async function ensureBrain() {
        if (brainVip.ready) return;
        await new Promise((res, rej) => {
            const t = setTimeout(() => rej(new Error('Brain no disponible')), 10_000);
            const i = setInterval(() => {
                if (brainVip.ready) { clearInterval(i); clearTimeout(t); res(); }
            }, 300);
        });
    }

    /** Llama a brainVip.process con un mensaje estructurado y devuelve la respuesta */
    async function callBrain(systemHint, userMessage, historyHint = '') {
        await ensureBrain();
        const fullMsg = historyHint
            ? `${historyHint}\n\n${userMessage}`
            : userMessage;
        const result = await brainVip.process(fullMsg, [], null, {
            upgames_context: true,
            _systemOverride: systemHint,  // brain_vip.py lo honra si está presente
        });
        return result.response || result.message || '';
    }

    /** Intenta parsear JSON de la respuesta del brain; si falla devuelve raw */
    function safeParse(raw) {
        // Elimina posibles backticks de markdown
        const clean = raw.replace(/```json|```/gi, '').trim();
        try { return { ok: true, data: JSON.parse(clean) }; }
        catch { return { ok: false, raw: clean }; }
    }

    // ────────────────────────────────────────────────────────────────
    // POST /api/nexus/creator-mentor
    // Analiza un juego antes / después de publicarlo y da consejo
    // Body: { usuario, gameData: { titulo, descripcion, tags[], categoria, precio?, imagenes? } }
    // ────────────────────────────────────────────────────────────────
    app.post('/api/nexus/creator-mentor', requireAuth, async (req, res) => {
        try {
            const { usuario, gameData } = req.body;
            if (!usuario || !gameData?.titulo) {
                return res.status(400).json({ error: 'Se requiere usuario y gameData.titulo' });
            }

            // 1. Enriquecer con stats reales del creador
            const [stats, narrative] = await Promise.all([
                fetchUpGamesUserStats(usuario),
                buildBehavioralNarrative(usuario),
            ]);

            // 2. Obtener items populares en la misma categoría para comparativa
            let competencia = [];
            if (gameData.categoria) {
                try {
                    const r = await axios.get(
                        `${UPGAMES_API_BASE}/items?categoria=${encodeURIComponent(gameData.categoria)}&limit=5`,
                        { timeout: 5000 }
                    );
                    const items = Array.isArray(r.data) ? r.data : (r.data?.items || []);
                    competencia = items
                        .filter(i => i.status === 'aprobado')
                        .sort((a, b) => (b.descargasEfectivas || 0) - (a.descargasEfectivas || 0))
                        .slice(0, 5)
                        .map(i => ({
                            titulo: i.title,
                            descargas: i.descargasEfectivas || 0,
                            tags: i.tags || [],
                        }));
                } catch (_) { /* no crítico */ }
            }

            // 3. Construir contexto del creador
            const creatorCtx = stats
                ? `Creador "${usuario}": ${stats.publicacionesAprobadas} publicaciones aprobadas, ` +
                  `${stats.totalDescargas.toLocaleString()} descargas totales, ${stats.seguidores} seguidores.`
                : `Creador "${usuario}": sin historial previo.`;

            const compCtx = competencia.length
                ? `\nCompetencia en categoría ${gameData.categoria}:\n` +
                  competencia.map(c => `  - "${c.titulo}": ${c.descargas} descargas`).join('\n')
                : '';

            const behavCtx = narrative
                ? `\nComportamiento del creador en la plataforma: ${narrative}`
                : '';

            // 4. Prompt especializado — el brain responde en JSON estructurado
            const systemHint = `Eres NEXUS, IA especializada en UpGames.
Tu tarea: analizar el juego/contenido que el creador quiere publicar y darle feedback accionable.
Responde ÚNICAMENTE con un JSON válido con esta estructura exacta (sin backticks, sin texto fuera del JSON):
{
  "analisis": "string — evaluación honesta del potencial del contenido (2-3 frases)",
  "puntuacion": number (0-10 — puntuación de potencial),
  "mejoras": ["string", ...] — lista de 3-5 mejoras concretas y accionables,
  "estrategia_marketing": "string — cuándo y cómo publicarlo para maximizar visibilidad",
  "tags_sugeridos": ["string", ...] — tags adicionales recomendados,
  "estimacion_descargas": { "min": number, "max": number, "plazo": "string" },
  "alertas": ["string", ...] — posibles problemas (puede ser array vacío)
}`;

            const userMessage =
                `${creatorCtx}${compCtx}${behavCtx}\n\n` +
                `JUEGO A ANALIZAR:\n` +
                `Título: ${gameData.titulo}\n` +
                `Descripción: ${gameData.descripcion || '(sin descripción)'}\n` +
                `Categoría: ${gameData.categoria || '(no especificada)'}\n` +
                `Tags: ${(gameData.tags || []).join(', ') || '(sin tags)'}\n` +
                `Precio: ${gameData.precio != null ? `$${gameData.precio}` : 'Gratuito'}\n` +
                `Imágenes: ${gameData.imagenes?.length || 0} imagen(es)`;

            const raw = await callBrain(systemHint, userMessage);
            const parsed = safeParse(raw);

            if (parsed.ok) {
                return res.json({ ok: true, mentor: parsed.data, creatorStats: stats });
            }

            // Fallback: respuesta en texto plano
            return res.json({
                ok: true,
                mentor: {
                    analisis: parsed.raw,
                    puntuacion: null,
                    mejoras: [],
                    estrategia_marketing: '',
                    tags_sugeridos: [],
                    estimacion_descargas: { min: 0, max: 0, plazo: 'desconocido' },
                    alertas: [],
                },
                creatorStats: stats,
            });

        } catch (err) {
            console.error('[/api/nexus/creator-mentor]', err.message);
            res.status(500).json({ error: 'Error en mentor de creador', detalle: err.message });
        }
    });

    // ────────────────────────────────────────────────────────────────
    // POST /api/nexus/fraud-analyze
    // Analiza patrones y devuelve un score de riesgo con razonamiento
    // Body: { usuario, patrones: { descargaVelocidad, reportesPrevios, accountAgeDays,
    //                              ipsDiferentes, actividadNocturna, descargasSinView } }
    // Requiere: verificarAdmin
    // ────────────────────────────────────────────────────────────────
    app.post('/api/nexus/fraud-analyze', requireCreator, async (req, res) => {
        try {
            const { usuario, patrones = {} } = req.body;
            if (!usuario) return res.status(400).json({ error: 'usuario requerido' });

            // Historial del usuario en Nexus DB
            let eventHistory = [];
            if (db) {
                const desde = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
                eventHistory = await db.collection('upgames_eventos')
                    .find({ usuario, ts: { $gte: desde } })
                    .sort({ ts: -1 })
                    .limit(100)
                    .toArray();
            }

            const eventSummary = (() => {
                if (!eventHistory.length) return 'Sin historial de eventos en los últimos 30 días.';
                const counts = eventHistory.reduce((acc, ev) => {
                    acc[ev.tipo] = (acc[ev.tipo] || 0) + 1;
                    return acc;
                }, {});
                return Object.entries(counts)
                    .map(([tipo, n]) => `${tipo}: ${n}`)
                    .join(', ');
            })();

            const systemHint = `Eres NEXUS, sistema de análisis de fraude para UpGames.
Analiza los patrones del usuario y determina nivel de riesgo.
Responde ÚNICAMENTE con un JSON válido (sin backticks):
{
  "riesgo": number (0.0 a 1.0 — probabilidad de actividad fraudulenta),
  "nivel": "bajo" | "medio" | "alto" | "critico",
  "razon": "string — explicación clara del razonamiento (2-3 frases)",
  "señales_detectadas": ["string", ...] — señales concretas que elevan el riesgo,
  "accion_recomendada": "permitir" | "monitorear" | "revisar_manualmente" | "bloquear",
  "confianza": number (0.0 a 1.0 — confianza en el análisis dado la información disponible)
}`;

            const userMessage =
                `Usuario analizado: "${usuario}"\n\n` +
                `Patrones de comportamiento:\n` +
                `  • Velocidad de descarga: ${patrones.descargaVelocidad ?? 'N/A'} descargas/hora\n` +
                `  • Reportes previos: ${patrones.reportesPrevios ?? 0}\n` +
                `  • Edad de cuenta: ${patrones.accountAgeDays ?? 'desconocida'} días\n` +
                `  • IPs diferentes detectadas: ${patrones.ipsDiferentes ?? 'desconocido'}\n` +
                `  • Actividad nocturna inusual: ${patrones.actividadNocturna ? 'Sí' : 'No'}\n` +
                `  • Descargas sin vista previa: ${patrones.descargasSinView ?? 0}\n\n` +
                `Historial de eventos (últimos 30 días): ${eventSummary}`;

            const raw = await callBrain(systemHint, userMessage);
            const parsed = safeParse(raw);

            if (parsed.ok) {
                // Guardar análisis en DB para auditoría
                if (db) {
                    db.collection('nexus_fraud_analysis').insertOne({
                        usuario, patrones, analisis: parsed.data, ts: new Date()
                    }).catch(() => {});
                }
                return res.json({ ok: true, analisis: parsed.data });
            }

            return res.json({
                ok: true,
                analisis: {
                    riesgo: 0.5, nivel: 'medio',
                    razon: parsed.raw,
                    señales_detectadas: [],
                    accion_recomendada: 'revisar_manualmente',
                    confianza: 0.3,
                },
            });

        } catch (err) {
            console.error('[/api/nexus/fraud-analyze]', err.message);
            res.status(500).json({ error: 'Error en análisis de fraude', detalle: err.message });
        }
    });

    // ────────────────────────────────────────────────────────────────
    // GET /api/nexus/creator-analytics/:username
    // Insights predictivos y accionables para el creador
    // Requiere: requireAuth
    // ────────────────────────────────────────────────────────────────
    app.get('/api/nexus/creator-analytics/:username', requireAuth, async (req, res) => {
        try {
            const { username } = req.params;
            if (!username) return res.status(400).json({ error: 'username requerido' });

            // Solo el propio usuario o admin puede ver sus analytics
            const isSelf = req.user?.username === username;
            const isAdmin = req.user?.isAdmin || req.user?.isCreator;
            if (!isSelf && !isAdmin) {
                return res.status(403).json({ error: 'Sin permiso para ver analytics de otro usuario' });
            }

            // Recopilar datos en paralelo
            const [stats, narrative] = await Promise.all([
                fetchUpGamesUserStats(username),
                buildBehavioralNarrative(username),
            ]);

            // Historial detallado de eventos en Nexus DB
            let eventData = { byDay: {}, byHour: {}, topCategories: {}, totalEvents: 0 };
            if (db) {
                const desde = new Date(Date.now() - 60 * 24 * 60 * 60 * 1000);
                const eventos = await db.collection('upgames_eventos')
                    .find({ usuario: username, ts: { $gte: desde } })
                    .sort({ ts: -1 }).limit(500).toArray();

                eventData.totalEvents = eventos.length;
                for (const ev of eventos) {
                    const d = ev.datos || {};
                    const date = new Date(ev.ts);
                    const dayKey = date.toLocaleDateString('es-CO', { weekday: 'long' });
                    const hourKey = date.getHours();
                    eventData.byDay[dayKey] = (eventData.byDay[dayKey] || 0) + 1;
                    eventData.byHour[hourKey] = (eventData.byHour[hourKey] || 0) + 1;
                    if (d.category) {
                        eventData.topCategories[d.category] = (eventData.topCategories[d.category] || 0) + 1;
                    }
                }
            }

            const bestDay = Object.entries(eventData.byDay)
                .sort((a, b) => b[1] - a[1])[0]?.[0] || 'sin datos';
            const bestHour = (() => {
                const [h] = Object.entries(eventData.byHour).sort((a, b) => b[1] - a[1])[0] || [null];
                if (h == null) return 'sin datos';
                const hr = parseInt(h);
                return `${hr}:00 - ${hr + 2}:00`;
            })();

            const statsCtx = stats
                ? `El creador "${username}" tiene: ${stats.publicacionesAprobadas} publicaciones, ` +
                  `${stats.totalDescargas.toLocaleString()} descargas totales, ${stats.seguidores} seguidores. ` +
                  `Sus mejores items: ${stats.topItems.map(i => `"${i.titulo}" (${i.descargas} descargas)`).join(', ')}.`
                : `El creador "${username}" no tiene publicaciones aún.`;

            const activityCtx =
                `Actividad de su audiencia: mayor engagement los ${bestDay}s, ` +
                `hora pico: ${bestHour}. ` +
                `Categorías más populares entre sus seguidores: ` +
                Object.entries(eventData.topCategories)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 3)
                    .map(([c]) => c)
                    .join(', ') || 'sin datos';

            const systemHint = `Eres NEXUS, analista de datos de UpGames.
Genera insights predictivos y accionables para el creador basándote en sus datos reales.
Responde ÚNICAMENTE con un JSON válido (sin backticks):
{
  "resumen_ejecutivo": "string — evaluación del estado actual del creador (2 frases)",
  "mejor_momento_publicar": {
    "dia": "string",
    "hora": "string",
    "razon": "string"
  },
  "categorias_recomendadas": ["string", ...] — 2-3 categorías donde debería publicar más,
  "tendencias": ["string", ...] — 3 tendencias actuales que debería aprovechar,
  "estimacion_proximo_mes": {
    "descargas": number,
    "nuevos_seguidores": number,
    "confianza": "baja" | "media" | "alta"
  },
  "acciones_prioritarias": ["string", ...] — 3-5 acciones concretas ordenadas por impacto,
  "punto_fuerte": "string — en qué destaca este creador",
  "punto_a_mejorar": "string — qué debería cambiar urgentemente"
}`;

            const userMessage = `${statsCtx}\n\n${activityCtx}\n\n` +
                (narrative ? `Comportamiento del creador: ${narrative}` : '');

            const raw = await callBrain(systemHint, userMessage);
            const parsed = safeParse(raw);

            const response = {
                ok: true,
                username,
                statsReales: stats,
                actividad: {
                    mejorDia: bestDay,
                    mejorHora: bestHour,
                    categoriasAudiencia: Object.entries(eventData.topCategories)
                        .sort((a, b) => b[1] - a[1]).slice(0, 5)
                        .map(([nombre, n]) => ({ nombre, eventos: n })),
                    totalEventos60dias: eventData.totalEvents,
                },
                insights: parsed.ok ? parsed.data : { resumen_ejecutivo: parsed.raw },
                generadoEn: new Date().toISOString(),
            };

            res.json(response);

        } catch (err) {
            console.error('[/api/nexus/creator-analytics]', err.message);
            res.status(500).json({ error: 'Error generando analytics', detalle: err.message });
        }
    });

    console.log('🔗 Rutas Nexus↔UpGames registradas: creator-mentor | fraud-analyze | creator-analytics');
}

module.exports = { registerNexusUpgamesRoutes };
