require('dotenv').config();
const express     = require('express');
const cors        = require('cors');
const axios       = require('axios');
const cheerio     = require('cheerio');
const path        = require('path');
const { spawn }   = require('child_process');
const fs          = require('fs').promises;
const fsSync      = require('fs');
const MongoClient = require('mongodb').MongoClient;
const bcrypt      = require('bcryptjs');
const jwt         = require('jsonwebtoken');
const crypto      = require('crypto');

// ── Multipart / File Upload ──────────────────────────────────────────
let multer, sharp, mammoth, pdfParse;
try { multer   = require('multer');   } catch(e) { console.warn('⚠️  multer no disponible'); }
try { sharp    = require('sharp');    } catch(e) { console.warn('⚠️  sharp no disponible'); }
try { mammoth  = require('mammoth');  } catch(e) { console.warn('⚠️  mammoth no disponible'); }
try { pdfParse = require('pdf-parse'); } catch(e) { console.warn('⚠️  pdf-parse no disponible'); }

// ── Upload dirs ─────────────────────────────────────────────────────
const UPLOAD_DIR   = path.join(__dirname, 'uploads_tmp');
const GENERATED_DIR= path.join(__dirname, 'generated');
[UPLOAD_DIR, GENERATED_DIR].forEach(d => { try { fsSync.mkdirSync(d, { recursive: true }); } catch(e){} });

// Multer storage — guardar en disco temporal
const _multerStorage = multer ? multer.diskStorage({
    destination: (req, file, cb) => cb(null, UPLOAD_DIR),
    filename:    (req, file, cb) => cb(null, `${Date.now()}_${crypto.randomBytes(6).toString('hex')}${path.extname(file.originalname)}`)
}) : null;
const upload = multer ? multer({
    storage: _multerStorage,
    limits:  { fileSize: 50 * 1024 * 1024 }, // 50 MB
    fileFilter: (req, file, cb) => {
        const allowed = [
            'image/jpeg','image/png','image/gif','image/webp','image/svg+xml',
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/plain','text/html','text/css','application/javascript',
            'application/json','text/csv','application/xml','text/xml',
            'application/x-python','text/x-python',
            'application/zip','application/x-zip-compressed'
        ];
        const ext = path.extname(file.originalname).toLowerCase();
        const extraExts = ['.py','.js','.ts','.jsx','.tsx','.cpp','.c','.h','.cs','.java',
                           '.go','.rs','.php','.rb','.swift','.kt','.sh','.bash','.sql',
                           '.yaml','.yml','.toml','.env','.md','.mdx','.txt','.csv',
                           '.html','.css','.json','.xml','.svg','.zip','.pdf','.docx','.xlsx'];
        if (allowed.includes(file.mimetype) || extraExts.includes(ext)) { cb(null, true); }
        else { cb(new Error(`Tipo de archivo no soportado: ${file.mimetype}`)); }
    }
}) : null;

const app  = express();
const PORT = process.env.PORT || 3000;
const JWT_SECRET = process.env.JWT_SECRET || 'nexus_fallback_secret_change_in_prod';

// ── Configuración de pagos ─────────────────────────────────────────
const PAYPAL_EMAIL     = 'jhonatandavidcastrogalviz@gmail.com';
const PLAN_PRICE       = 10.00;
const PLAN_CURRENCY    = 'USD';
const FREE_MSG_PER_DAY = 10;
const FREE_GEN_PER_DAY = 5;   // archivos CodeGen + imágenes generadas (plan free)
const PLAN_DURATION_MS = 30 * 24 * 60 * 60 * 1000;

// ── Contador diario de generaciones para plan Free ─────────────────
// Persistido en MongoDB (colección daily_usage) — sobrevive reinicios
// Documento: { userId, date: 'YYYY-MM-DD', count: N }

async function getFreeGenToday(userId) {
    if (!db) return 0;
    const today = new Date().toISOString().slice(0, 10);
    const doc = await db.collection('daily_usage').findOne({ userId, date: today });
    return doc ? doc.count : 0;
}

async function incrementFreeGen(userId) {
    if (!db) return;
    const today = new Date().toISOString().slice(0, 10);
    await db.collection('daily_usage').updateOne(
        { userId, date: today },
        { $inc: { count: 1 }, $setOnInsert: { userId, date: today } },
        { upsert: true }
    );
}

// ── Cuentas VIP permanentes ────────────────────────────────────────
const VIP_ACCOUNTS = [
  'jhonatandavidcastrogalviz@gmail.com',
  'theimonsterl141@gmail.com'
];

// ── Stores en memoria (anti-fraude) ───────────────────────────────
const rateLimitStore = new Map();
const loginAttempts  = new Map();

app.use(cors());
app.use(express.json({ limit: '100mb' }));
app.use(express.urlencoded({ extended: true, limit: '100mb' }));
app.use(express.static('public'));
app.use('/generated', express.static(GENERATED_DIR));
app.use((req, res, next) => { res.setTimeout(600000); next(); }); // 10 min timeout para generación de archivos grandes

// ══════════════════════════════════════════════════════════════════
//  BASE DE DATOS
// ══════════════════════════════════════════════════════════════════
let db = null;

async function connectDB() {
    if (!process.env.MONGODB_URI) return;
    try {
        const client = await MongoClient.connect(process.env.MONGODB_URI, { serverSelectionTimeoutMS: 10000 });
        db = client.db(process.env.MONGODB_DB_NAME || 'nexus');
        await Promise.all([
            db.collection('messages').createIndex({ conversationId: 1, ts: 1 }),
            db.collection('messages').createIndex({ userId: 1, ts: -1 }),
            db.collection('clicks').createIndex({ query: 1, ts: -1 }),
            db.collection('searches').createIndex({ ts: -1 }),
            db.collection('users').createIndex({ email: 1 }, { unique: true }),
            db.collection('users').createIndex({ username: 1 }, { unique: true }),
            db.collection('payments').createIndex({ transactionId: 1 }, { unique: true }),
            db.collection('payments').createIndex({ userId: 1, ts: -1 }),
            db.collection('fraud_log').createIndex({ ts: -1 }),
            db.collection('fraud_log').createIndex({ ip: 1, ts: -1 }),
            db.collection('used_transactions').createIndex({ transactionId: 1 }, { unique: true }),
            db.collection('fraud_blacklist').createIndex({ email: 1 }),
            db.collection('daily_usage').createIndex({ userId: 1, date: 1 }, { unique: true }),
        ]);
        console.log('✅ MongoDB conectado');
        setInterval(runMonthlyCheck, 60 * 60 * 1000);
        runMonthlyCheck();
    } catch (e) {
        console.warn('⚠️  MongoDB no disponible:', e.message);
    }
}

// ══════════════════════════════════════════════════════════════════
//  VERIFICACIÓN MENSUAL — degradar planes vencidos
// ══════════════════════════════════════════════════════════════════
async function runMonthlyCheck() {
    if (!db) return;
    try {
        const now = new Date();
        const expired = await db.collection('users').find({
            plan: 'premium',
            isVip: { $ne: true },
            planExpiresAt: { $lt: now }
        }).toArray();
        for (const user of expired) {
            await db.collection('users').updateOne(
                { _id: user._id },
                { $set: { plan: 'free', planExpired: true, planDegradedAt: now } }
            );
            console.log(`📉 Plan degradado a FREE: ${user.email}`);
        }
        if (expired.length > 0) console.log(`✅ Verificación mensual: ${expired.length} plan(es) degradado(s)`);
    } catch (e) { console.error('[monthlyCheck]', e.message); }
}

// ══════════════════════════════════════════════════════════════════
//  ANTI-FRAUDE
// ══════════════════════════════════════════════════════════════════
function getClientIP(req) {
    return (
        req.headers['x-forwarded-for']?.split(',')[0]?.trim() ||
        req.headers['x-real-ip'] ||
        req.connection?.remoteAddress ||
        req.socket?.remoteAddress ||
        '0.0.0.0'
    );
}

async function logFraud(type, details, req) {
    console.warn(`🚨 FRAUDE [${type}]`, details);
    if (!db) return;
    try {
        await db.collection('fraud_log').insertOne({
            type, ip: getClientIP(req), ua: req.headers['user-agent'] || '', details, ts: new Date()
        });
    } catch (e) {}
}

function checkRateLimit(req, res, maxReq = 100, windowMs = 60000) {
    const ip  = getClientIP(req);
    const now = Date.now();
    const entry = rateLimitStore.get(ip);
    if (!entry || now > entry.resetAt) {
        rateLimitStore.set(ip, { count: 1, resetAt: now + windowMs });
        return true;
    }
    entry.count++;
    if (entry.count > maxReq) {
        res.status(429).json({ error: 'Demasiadas solicitudes. Espera un momento.' });
        return false;
    }
    return true;
}

function checkLoginAttempts(req, res, identifier) {
    const ip  = getClientIP(req);
    const key = `${ip}:${identifier}`;
    const now = Date.now();
    const entry = loginAttempts.get(key);
    if (entry && now < entry.lockedUntil) {
        const minLeft = Math.ceil((entry.lockedUntil - now) / 60000);
        res.status(429).json({ error: `Cuenta bloqueada por intentos fallidos. Intenta en ${minLeft} min.` });
        return false;
    }
    return true;
}

function recordFailedLogin(req, identifier) {
    const ip  = getClientIP(req);
    const key = `${ip}:${identifier}`;
    const now = Date.now();
    const entry = loginAttempts.get(key) || { count: 0, lockedUntil: 0 };
    entry.count++;
    if (entry.count >= 5) {
        entry.lockedUntil = now + 15 * 60 * 1000;
        logFraud('brute_force_login', { identifier, attempts: entry.count }, { headers: {}, connection: { remoteAddress: ip } });
    }
    loginAttempts.set(key, entry);
}

function clearFailedLogins(req, identifier) {
    loginAttempts.delete(`${getClientIP(req)}:${identifier}`);
}

function isValidPaypalTxId(txId) {
    return /^[A-Z0-9]{13,25}$/.test(txId.trim().toUpperCase());
}

async function detectFraudPatterns(userId, transactionId, payerEmail, req) {
    if (!db) return { ok: true };
    const ip      = getClientIP(req);
    const now     = new Date();
    const hourAgo = new Date(now - 60 * 60 * 1000);
    const dayAgo  = new Date(now - 24 * 60 * 60 * 1000);

    // 1. Transacción ya usada en otra cuenta
    const txUsed = await db.collection('used_transactions').findOne({ transactionId });
    if (txUsed) {
        await logFraud('duplicate_transaction', { transactionId, originalUserId: txUsed.userId, attemptUserId: userId }, req);
        return { ok: false, reason: 'Esta transacción ya fue utilizada en otra cuenta.' };
    }

    // 2. Múltiples verificaciones desde la misma IP en la última hora (max 3)
    const ipVerifications = await db.collection('payments').countDocuments({ ip, ts: { $gte: hourAgo } });
    if (ipVerifications >= 3) {
        await logFraud('ip_payment_flood', { ip, count: ipVerifications }, req);
        return { ok: false, reason: 'Demasiados intentos de pago desde esta IP. Intenta más tarde.' };
    }

    // 3. Usuario con más de 5 intentos de verificación en 24h (spam de txIds falsos)
    const userFraudAttempts = await db.collection('fraud_log').countDocuments({ 'details.userId': userId, ts: { $gte: dayAgo } });
    if (userFraudAttempts >= 5) {
        await logFraud('user_payment_spam', { userId }, req);
        return { ok: false, reason: 'Demasiados intentos fallidos. Contacta soporte.' };
    }

    // 4. Email del pagador en lista negra
    if (payerEmail) {
        const blacklisted = await db.collection('fraud_blacklist').findOne({ email: payerEmail.toLowerCase() });
        if (blacklisted) {
            await logFraud('blacklisted_payer', { payerEmail }, req);
            return { ok: false, reason: 'El email del pagador está reportado como fraudulento.' };
        }
    }

    // 5. Mismo email pagador usado en más de 3 cuentas distintas
    if (payerEmail) {
        const samePayerAccounts = await db.collection('payments').distinct('userId', {
            payerEmail: payerEmail.toLowerCase(), verified: true
        });
        if (samePayerAccounts.length >= 3) {
            await logFraud('payer_multi_account', { payerEmail, accounts: samePayerAccounts.length }, req);
            return { ok: false, reason: 'Este email de PayPal ya fue usado en demasiadas cuentas.' };
        }
    }

    // 6. Formato de txId inválido (no es un ID real de PayPal)
    if (!isValidPaypalTxId(transactionId)) {
        await logFraud('invalid_tx_format', { transactionId, userId }, req);
        return { ok: false, reason: 'ID de transacción con formato inválido. Verifica que lo copiaste correctamente de PayPal.' };
    }

    // 7. Misma IP con más de 2 cuentas creadas en 24h (cuentas falsas masivas)
    const ipAccounts = await db.collection('users').countDocuments({ registrationIp: ip, createdAt: { $gte: dayAgo } });
    if (ipAccounts >= 3) {
        await logFraud('ip_account_farm', { ip, count: ipAccounts }, req);
        return { ok: false, reason: 'Demasiadas cuentas creadas desde esta red. Contacta soporte.' };
    }

    // 8. TxId con caracteres repetidos (ej: AAAAAAAAAAAAAAAA — obviamente falso)
    if (/^(.)\1{8,}$/.test(transactionId.trim())) {
        await logFraud('fake_tx_pattern', { transactionId, userId }, req);
        return { ok: false, reason: 'ID de transacción inválido.' };
    }

    return { ok: true };
}

// ══════════════════════════════════════════════════════════════════
//  AUTH MIDDLEWARE
// ══════════════════════════════════════════════════════════════════
function authMiddleware(req, res, next) {
    const auth = req.headers['authorization'];
    if (!auth || !auth.startsWith('Bearer ')) { req.user = null; return next(); }
    try { req.user = jwt.verify(auth.slice(7), JWT_SECRET); }
    catch (e) { req.user = null; }
    next();
}

function requireAuth(req, res, next) {
    if (!req.user) return res.status(401).json({ error: 'No autenticado' });
    next();
}

app.use(authMiddleware);

// ══════════════════════════════════════════════════════════════════
//  PROCESO PYTHON (cerebro neural)
// ══════════════════════════════════════════════════════════════════
class BrainProcess {
    /**
     * @param {string} scriptName  nombre del archivo en /neural/ (ej. 'brain.py' | 'brain_vip.py')
     * @param {string} label       etiqueta para logs
     */
    constructor(scriptName = 'brain.py', label = 'BASE') {
        this.scriptName = scriptName;
        this.label = label;
        this.proc = null; this.queue = []; this.ready = false;
        this.restarts = 0; this.stats = {}; this.requestCounter = 0;
        this.lastOllamaError = 0; this.ollamaErrorCount = 0;
        this._cachedStats = null; this._statsUpdating = false;
        this._start();
    }

    _start() {
        const brainPath = path.join(__dirname, 'neural', this.scriptName);
        const env = { ...process.env, PYTHONUNBUFFERED: '1' };
        console.log(`🧠 Iniciando cerebro NEXUS [${this.label}] → ${this.scriptName}`);
        this.proc = spawn('python3', ['-u', brainPath], { env });

        let buffer = '';
        this.proc.stdout.on('data', (chunk) => {
            buffer += chunk.toString();
            const parts = buffer.split('\n');
            buffer = parts.pop();
            for (const part of parts) {
                const line = part.trim();
                if (!line) continue;
                if (line.startsWith('✓') || line.startsWith('⚠') || line.startsWith('[')) {
                    console.log('🐍', line);
                    if (line.includes('listo') || line.includes('ready')) this.ready = true;
                    continue;
                }
                try {
                    const response = JSON.parse(line);
                    const requestId = response._requestId;
                    if (requestId) {
                        const idx = this.queue.findIndex(p => p.requestId === requestId);
                        if (idx !== -1) { const p = this.queue.splice(idx,1)[0]; clearTimeout(p.timeoutId); delete response._requestId; p.resolve(response); }
                    } else {
                        const p = this.queue.shift();
                        if (p) { clearTimeout(p.timeoutId); p.resolve(response); }
                    }
                } catch (e) {
                    const p = this.queue.shift();
                    if (p) { clearTimeout(p.timeoutId); p.reject(new Error('JSON parse error')); }
                }
            }
        });

        this.proc.stderr.on('data', (d) => {
            const msg = d.toString().trim();
            if (msg.includes('Ollama') && msg.includes('HTTP Error 500')) {
                if (Date.now() - this.lastOllamaError > 10000) {
                    console.error('⚠️  Ollama error (Smart Mode)');
                    this.lastOllamaError = Date.now(); this.ollamaErrorCount++;
                }
                return;
            }
            if (msg.includes('ResponseGen') && msg.includes('fallback')) return;
            if (msg && !msg.includes('UserWarning')) console.error('🐍 ERR:', msg);
        });

        this.proc.on('close', (code) => {
            console.warn(`⚠️  Brain [${this.label}] cerró (code=${code}). Reiniciando...`);
            this.ready = false;
            for (const p of this.queue) { clearTimeout(p.timeoutId); p.reject(new Error('Brain died')); }
            this.queue = []; this.restarts++;
            if (this.restarts < 15) setTimeout(() => this._start(), 2500);
        });
    }

    _send(data, timeoutMs = 120000) {
        return new Promise((resolve, reject) => {
            const requestId = `${Date.now()}_${this.requestCounter++}`;
            data._requestId = requestId;
            const timeoutId = setTimeout(() => {
                const idx = this.queue.findIndex(p => p.requestId === requestId);
                if (idx !== -1) this.queue.splice(idx, 1);
                reject(new Error('Brain timeout'));
            }, timeoutMs);
            this.queue.push({ resolve, reject, timeoutId, requestId });
            try { this.proc.stdin.write(JSON.stringify(data) + '\n'); }
            catch (e) {
                const idx = this.queue.findIndex(p => p.requestId === requestId);
                if (idx !== -1) this.queue.splice(idx, 1);
                clearTimeout(timeoutId); reject(e);
            }
        });
    }

    async process(msg, hist=[], sr=null, userCtx=null) { return this._send({ action:'process', message:msg, history:hist, search_results:sr, user_context:userCtx }, 120000); }
    async learn(msg, res, helpful=true, sr=[]) { return this._send({ action:'learn', message:msg, response:res, was_helpful:helpful, search_results:sr }, 10000); }
    async click(q, url, pos, dwell, bounced) { return this._send({ action:'click', query:q, url, position:pos, dwell_time:dwell, bounced:!!bounced }, 8000); }
    async proactive(userCtx=null) { return this._send({ action:'proactive_init', user_context:userCtx }, 30000); }

    async getStats() {
        if (this._cachedStats) {
            if (!this._statsUpdating) {
                this._statsUpdating = true;
                this._send({ action:'stats' }, 120000)
                    .then(s=>{ this._cachedStats=s; this.stats=s; })
                    .catch(()=>{})
                    .finally(()=>{ this._statsUpdating=false; });
            }
            return this._cachedStats;
        }
        const s = await this._send({ action:'stats' }, 120000);
        this._cachedStats = s; this.stats = s; return s;
    }

    shutdown() { if (this.proc) this.proc.kill('SIGTERM'); }
}

// ── Dos instancias del cerebro ─────────────────────────────────────
// brainBase  → brain.py     (usuarios free)
// brainVip   → brain_vip.py (premium / VIP / creador)
const brainBase = new BrainProcess('brain.py',     'BASE');
const brainVip  = new BrainProcess('brain_vip.py', 'ULTRA');

// Alias de compatibilidad para rutas que no dependen del plan
const brain = brainBase;

process.on('SIGTERM', () => { brainBase.shutdown(); brainVip.shutdown(); if (db) db.client?.close(); process.exit(0); });
process.on('SIGINT',  () => { brainBase.shutdown(); brainVip.shutdown(); if (db) db.client?.close(); process.exit(0); });

// ══════════════════════════════════════════════════════════════════
//  BÚSQUEDA WEB
// ══════════════════════════════════════════════════════════════════
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36';
const HEADERS = { 'User-Agent': UA, 'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8' };

async function searchDDG(query) {
    try {
        const q = encodeURIComponent(query.trim());
        const r = await axios.get('https://api.duckduckgo.com/', { params:{q,format:'json',no_html:1,skip_disambig:1}, headers:HEADERS, timeout:6000 });
        const results=[]; const d=r.data;
        if (d.AbstractText) results.push({ title:d.Heading||query, url:d.AbstractURL||'', description:d.AbstractText, snippet:d.AbstractText, source:d.AbstractSource||'Wikipedia' });
        for (const t of (d.RelatedTopics||[])) { if (t.FirstURL&&t.Text) { results.push({ title:t.Text.split(' - ')[0].slice(0,90), url:t.FirstURL, description:t.Text, snippet:t.Text, source:'DuckDuckGo' }); if (results.length>=6) break; } }
        return results;
    } catch { return []; }
}

async function searchBing(query) {
    try {
        const q = encodeURIComponent(query.trim());
        const r = await axios.get(`https://www.bing.com/search?q=${q}&setlang=es`, { headers:HEADERS, timeout:8000 });
        const $ = cheerio.load(r.data); const results=[];
        $('.b_algo').each((i,el)=>{
            if (results.length>=7) return false;
            const te=$(el).find('h2 a'), de=$(el).find('.b_caption p,.b_algoSlug');
            const title=te.text().trim(), href=te.attr('href'), desc=de.first().text().trim();
            if (title&&href&&href.startsWith('http')) results.push({ title, url:href, description:desc, snippet:desc, source:'Bing' });
        });
        return results;
    } catch { return []; }
}

async function searchAll(query) {
    const [ddg,bing] = await Promise.allSettled([searchDDG(query), searchBing(query)]);
    const all=[...(ddg.status==='fulfilled'?ddg.value:[]), ...(bing.status==='fulfilled'?bing.value:[])];
    const seen=new Set();
    return all.filter(r=>r.url&&!seen.has(r.url)&&seen.add(r.url));
}

// ══════════════════════════════════════════════════════════════════
//  HELPERS PLAN
// ══════════════════════════════════════════════════════════════════
// ── Emails del creador (acceso total + trato especial) ────────────
const CREATOR_EMAILS = [
    'jhonatandavidcastrogalviz@gmail.com',
    'theimonsterl141@gmail.com'
];

function isVipAccount(email) {
    return VIP_ACCOUNTS.includes(email?.toLowerCase()?.trim());
}

function isCreatorAccount(email) {
    return CREATOR_EMAILS.includes(email?.toLowerCase()?.trim());
}

async function getPlanStatus(user) {
    if (!user) return { plan:'free', active:false };
    if (user.isVip || isVipAccount(user.email)) return { plan:'premium', active:true, isVip:true, expiresAt:null };
    if (user.plan==='premium' && user.planExpiresAt) {
        if (new Date(user.planExpiresAt) > new Date()) return { plan:'premium', active:true, isVip:false, expiresAt:user.planExpiresAt };
        if (db) await db.collection('users').updateOne({ _id:user._id }, { $set:{ plan:'free', planExpired:true } });
        return { plan:'free', active:false, expired:true };
    }
    return { plan:'free', active:false };
}

async function getMessagesToday(userId) {
    if (!db) return 0;
    const today = new Date(); today.setHours(0,0,0,0);
    return db.collection('messages').countDocuments({ userId, role:'user', ts:{ $gte:today } });
}

function generateToken(user) {
    return jwt.sign(
        {
            id:        user._id.toString(),
            email:     user.email,
            username:  user.username,
            plan:      user.plan||'free',
            isVip:     user.isVip || isVipAccount(user.email),
            isCreator: isCreatorAccount(user.email)
        },
        JWT_SECRET,
        { expiresIn:'30d' }
    );
}

function sanitizeUser(user) {
    return {
        id:          user._id.toString(),
        email:       user.email,
        username:    user.username,
        displayName: user.displayName || user.username,
        createdAt:   user.createdAt,
        isVip:       user.isVip || isVipAccount(user.email),
        isCreator:   isCreatorAccount(user.email)
    };
}

// ══════════════════════════════════════════════════════════════════
//  RUTAS AUTH
// ══════════════════════════════════════════════════════════════════

// POST /api/auth/register
app.post('/api/auth/register', async (req, res) => {
    if (!checkRateLimit(req, res, 10, 60000)) return;
    const { email, username, password } = req.body;
    if (!email||!username||!password) return res.status(400).json({ error:'Email, usuario y contraseña requeridos' });
    if (password.length<6) return res.status(400).json({ error:'Contraseña mínimo 6 caracteres' });
    if (username.length<3) return res.status(400).json({ error:'Usuario mínimo 3 caracteres' });
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return res.status(400).json({ error:'Email inválido' });
    if (!/^[a-zA-Z0-9_.-]{3,30}$/.test(username)) return res.status(400).json({ error:'Usuario: solo letras, números, _, -, . (3-30 chars)' });
    if (!db) return res.status(503).json({ error:'Base de datos no disponible' });
    try {
        const exists = await db.collection('users').findOne({ $or:[{ email:email.toLowerCase() },{ username:username.toLowerCase() }] });
        if (exists) {
            if (exists.email===email.toLowerCase()) return res.status(409).json({ error:'El email ya está registrado' });
            return res.status(409).json({ error:'El nombre de usuario ya está en uso' });
        }
        const isVip = isVipAccount(email);
        const hash  = await bcrypt.hash(password, 12);
        const result = await db.collection('users').insertOne({
            email:email.toLowerCase(), username:username.toLowerCase(), displayName:username,
            password:hash, plan:isVip?'premium':'free', isVip,
            planExpiresAt:null, createdAt:new Date(), updatedAt:new Date(), registrationIp:getClientIP(req)
        });
        const user  = await db.collection('users').findOne({ _id:result.insertedId });
        const token = generateToken(user);
        const planStatus = await getPlanStatus(user);
        const msgsToday  = planStatus.plan==='free' ? 0 : null;
        res.json({ token, user:sanitizeUser(user), plan:planStatus, messagesUsed:msgsToday, messagesLimit:FREE_MSG_PER_DAY });
    } catch (e) { console.error('[register]',e.message); res.status(500).json({ error:'Error al registrar' }); }
});

// POST /api/auth/login
app.post('/api/auth/login', async (req, res) => {
    if (!checkRateLimit(req, res, 20, 60000)) return;
    const { identifier, password } = req.body;
    if (!identifier||!password) return res.status(400).json({ error:'Credenciales requeridas' });
    if (!db) return res.status(503).json({ error:'Base de datos no disponible' });
    if (!checkLoginAttempts(req, res, identifier)) { await logFraud('login_blocked',{ identifier },req); return; }
    try {
        const id   = identifier.toLowerCase().trim();
        const user = await db.collection('users').findOne({ $or:[{ email:id },{ username:id }] });
        if (!user) { recordFailedLogin(req,identifier); return res.status(401).json({ error:'Credenciales incorrectas' }); }
        const valid = await bcrypt.compare(password, user.password);
        if (!valid) { recordFailedLogin(req,identifier); await logFraud('failed_login',{ identifier, userId:user._id.toString() },req); return res.status(401).json({ error:'Credenciales incorrectas' }); }
        clearFailedLogins(req, identifier);
        if (isVipAccount(user.email) && !user.isVip) {
            await db.collection('users').updateOne({ _id:user._id },{ $set:{ isVip:true, plan:'premium' } });
            user.isVip=true; user.plan='premium';
        }
        await db.collection('users').updateOne({ _id:user._id },{ $set:{ lastLoginAt:new Date(), lastLoginIp:getClientIP(req) } });
        const token     = generateToken(user);
        const planStatus= await getPlanStatus(user);
        const msgsToday = planStatus.plan==='free' ? await getMessagesToday(user._id.toString()) : null;
        res.json({ token, user:sanitizeUser(user), plan:planStatus, messagesUsed:msgsToday, messagesLimit:FREE_MSG_PER_DAY });
    } catch (e) { console.error('[login]',e.message); res.status(500).json({ error:'Error al iniciar sesión' }); }
});

// GET /api/auth/me
app.get('/api/auth/me', requireAuth, async (req, res) => {
    if (!db) return res.status(503).json({ error:'BD no disponible' });
    try {
        const { ObjectId } = require('mongodb');
        const user = await db.collection('users').findOne({ _id:new ObjectId(req.user.id) });
        if (!user) return res.status(404).json({ error:'Usuario no encontrado' });
        if (isVipAccount(user.email) && (!user.isVip||user.plan!=='premium')) {
            await db.collection('users').updateOne({ _id:user._id },{ $set:{ isVip:true, plan:'premium' } });
            user.isVip=true; user.plan='premium';
        }
        const planStatus = await getPlanStatus(user);
        const msgsToday  = planStatus.plan==='free' ? await getMessagesToday(user._id.toString()) : null;
        const resetsAt   = planStatus.plan==='free' ? (() => { const d=new Date(); d.setHours(24,0,0,0); return d; })() : null;
        res.json({ user:sanitizeUser(user), plan:planStatus, messagesUsed:msgsToday, messagesLimit:FREE_MSG_PER_DAY, resetsAt });
    } catch (e) { res.status(500).json({ error:'Error al obtener usuario' }); }
});

// PATCH /api/auth/profile
app.patch('/api/auth/profile', requireAuth, async (req, res) => {
    const { displayName, username } = req.body;
    if (!db) return res.status(503).json({ error:'BD no disponible' });
    try {
        const { ObjectId } = require('mongodb');
        const updates = { updatedAt:new Date() };
        if (displayName!==undefined) {
            if (!displayName.trim()) return res.status(400).json({ error:'Nombre no puede estar vacío' });
            updates.displayName = displayName.trim().slice(0,50);
        }
        if (username!==undefined) {
            if (!/^[a-zA-Z0-9_.-]{3,30}$/.test(username)) return res.status(400).json({ error:'Usuario inválido' });
            const taken = await db.collection('users').findOne({ username:username.toLowerCase(), _id:{ $ne:new ObjectId(req.user.id) } });
            if (taken) return res.status(409).json({ error:'Nombre de usuario en uso' });
            updates.username = username.toLowerCase();
        }
        await db.collection('users').updateOne({ _id:new ObjectId(req.user.id) },{ $set:updates });
        const user  = await db.collection('users').findOne({ _id:new ObjectId(req.user.id) });
        const token = generateToken(user);
        res.json({ token, user:sanitizeUser(user) });
    } catch (e) { res.status(500).json({ error:'Error al actualizar perfil' }); }
});

// ══════════════════════════════════════════════════════════════════
//  RUTAS PAGO
// ══════════════════════════════════════════════════════════════════

// GET /api/payment/info
app.get('/api/payment/info', requireAuth, async (req, res) => {
    const { ObjectId } = require('mongodb');
    let user = null;
    if (db) user = await db.collection('users').findOne({ _id:new ObjectId(req.user.id) });
    const planStatus = user ? await getPlanStatus(user) : { plan:'free' };
    res.json({
        plan: planStatus.plan, isVip: planStatus.isVip||false, expiresAt: planStatus.expiresAt||null,
        method:'PayPal', paypalTarget:Buffer.from(PAYPAL_EMAIL).toString('base64'),
        amount:PLAN_PRICE.toFixed(2), currency:PLAN_CURRENCY, period:'mensual',
        description:'NEXUS AI — Plan Premium Mensual ($10 USD/mes)'
    });
});

// POST /api/payment/verify
app.post('/api/payment/verify', requireAuth, async (req, res) => {
    if (!checkRateLimit(req, res, 5, 60000)) return;
    const { transactionId, payerEmail } = req.body;
    if (!transactionId) return res.status(400).json({ error:'ID de transacción requerido' });
    if (!db) return res.status(503).json({ error:'BD no disponible' });

    const userId = req.user.id;
    const txId   = transactionId.trim().toUpperCase();

    try {
        const { ObjectId } = require('mongodb');
        const user = await db.collection('users').findOne({ _id:new ObjectId(userId) });

        // VIP no necesita pago
        if (user && (user.isVip||isVipAccount(user.email))) {
            return res.json({ ok:true, plan:'premium', isVip:true, message:'Cuenta VIP — acceso permanente sin pago.' });
        }

        // Anti-fraude
        const fraudCheck = await detectFraudPatterns(userId, txId, payerEmail?.toLowerCase(), req);
        if (!fraudCheck.ok) {
            await logFraud('payment_rejected',{ userId, transactionId:txId, reason:fraudCheck.reason },req);
            return res.status(403).json({ error:fraudCheck.reason });
        }

        // Registrar tx usada
        await db.collection('used_transactions').insertOne({ transactionId:txId, userId, ts:new Date() });

        const planExpiresAt = new Date(Date.now() + PLAN_DURATION_MS);

        await db.collection('payments').insertOne({
            userId, transactionId:txId, amount:PLAN_PRICE, currency:PLAN_CURRENCY,
            payerEmail:payerEmail?.toLowerCase()||'unknown', verified:true,
            ip:getClientIP(req), planExpiresAt, ts:new Date()
        });

        await db.collection('users').updateOne(
            { _id:new ObjectId(userId) },
            { $set:{ plan:'premium', planExpiresAt, planExpired:false, lastPaymentAt:new Date() } }
        );

        console.log(`✅ Premium activado: ${user?.email} → hasta ${planExpiresAt.toISOString()}`);
        res.json({ ok:true, plan:'premium', expiresAt:planExpiresAt, message:`¡Plan Premium activado! Válido hasta el ${planExpiresAt.toLocaleDateString('es')}.` });
    } catch (e) {
        if (e.code===11000) {
            await logFraud('duplicate_tx_attempt',{ userId, transactionId:txId },req);
            return res.status(409).json({ error:'Esta transacción ya fue registrada anteriormente.' });
        }
        console.error('[payment/verify]',e.message);
        res.status(500).json({ error:'Error al verificar pago' });
    }
});

// GET /api/payment/status
app.get('/api/payment/status', requireAuth, async (req, res) => {
    if (!db) return res.status(503).json({ error:'BD no disponible' });
    try {
        const { ObjectId } = require('mongodb');
        const user = await db.collection('users').findOne({ _id:new ObjectId(req.user.id) });
        if (!user) return res.status(404).json({ error:'Usuario no encontrado' });
        const planStatus = await getPlanStatus(user);
        const msgsToday  = planStatus.plan==='free' ? await getMessagesToday(req.user.id) : null;
        const resetsAt   = planStatus.plan==='free' ? (() => { const d=new Date(); d.setHours(24,0,0,0); return d; })() : null;
        res.json({ plan:planStatus, messagesUsed:msgsToday, messagesLimit:FREE_MSG_PER_DAY, resetsAt });
    } catch (e) { res.status(500).json({ error:'Error' }); }
});

// ══════════════════════════════════════════════════════════════════
//  CHAT
// ══════════════════════════════════════════════════════════════════
app.post('/api/chat', requireAuth, async (req, res) => {
    if (!checkRateLimit(req, res, 60, 60000)) return;
    const { message, conversationId, history } = req.body;
    if (!message?.trim()) return res.status(400).json({ error:'Mensaje vacío' });

    const userId = req.user.id;
    const { ObjectId } = require('mongodb');
    const user = db ? await db.collection('users').findOne({ _id:new ObjectId(userId) }) : null;
    const planStatus = user ? await getPlanStatus(user) : { plan:'free' };

    // ℹ️ Sin límite de mensajes en plan free — NEXUS aprende del usuario con el uso

    const convId = conversationId || `conv_${Date.now()}`;
    const userEmail = user?.email || req.user.email || '';
    const isCreator = isCreatorAccount(userEmail);
    const isVip     = user?.isVip || isVipAccount(userEmail);

    // ── Contexto de usuario para el brain ─────────────────────────
    const userContext = {
        userId,
        email:       userEmail,
        username:    user?.username || req.user.username || '',
        displayName: user?.displayName || user?.username || req.user.username || '',
        plan:        planStatus.plan,
        isVip,
        isCreator
    };

    console.log(`💬 [${convId.slice(-6)}] [${planStatus.plan}]${isCreator?' 👑 CREATOR':''} "${message.slice(0,70)}"`);

    // ── Detectar intent UpGames ──────────────────────────────────
    const UG_KEYWORDS = [
        'recomienda','recomiéndame','sugier','qué juego','que juego',
        'juegos de','busca juego','juego de terror','juego de zombi',
        'juego de accion','juego de acción','juego rpg','juego indie',
        'upgames','quiero jugar','para jugar','dame juegos','ver juegos',
        'qué hay','que hay','mostrar juegos','listar juegos',
        'similar a','parecido a','juegos gratis','juegos android','juegos pc',
        'juego de survival','juego de aventura','juego de pelea','juego multijugador',
        'qué tenemos','que tenemos','qué tienen','que tienen','nueva publicación',
        'recién subido','recien subido'
    ];
    const msgLower = message.toLowerCase();
    const isUpGamesQuery = UG_KEYWORDS.some(kw => msgLower.includes(kw));

    // ── Si pide juegos → buscar catálogo real en UpGames ─────────
    const UPGAMES_API = process.env.UPGAMES_API_URL || 'https://upgames-production.up.railway.app';
    let upgamesContext = '';
    if (isUpGamesQuery) {
        try {
            const ugResp = await axios.get(`${UPGAMES_API}/items`, { timeout: 7000 });
            const allItems = Array.isArray(ugResp.data) ? ugResp.data : [];
            const disponibles = allItems
                .filter(i => i.status === 'aprobado' && i.linkStatus !== 'caido')
                .slice(0, 20);

            if (disponibles.length > 0) {
                const lista = disponibles.map(i =>
                    `• "${i.title}" | Categoría: ${i.category||'General'} | Descargas: ${i.descargasEfectivas||0} | ID: ${i._id}`
                ).join('\n');
                upgamesContext = (
                    `\n\n[CATÁLOGO UPGAMES — JUEGOS REALES DISPONIBLES AHORA]\n` +
                    `Estos son los ${disponibles.length} contenidos reales en UpGames en este momento.\n` +
                    `REGLA CRÍTICA: Recomienda SOLO de esta lista. JAMÁS inventes juegos que no estén aquí.\n` +
                    `Si el usuario pide un género que no está disponible, díselo honestamente y sugiere lo más cercano de la lista.\n\n` +
                    lista +
                    `\n\nAdemás puedes:\n` +
                    `- Sugerir que el usuario filtre por categoría en la biblioteca\n` +
                    `- Indicar cuántas descargas tiene cada juego (popularidad)\n` +
                    `- Ayudar a encontrar algo específico con el buscador de la plataforma\n` +
                    `[FIN CATÁLOGO UPGAMES]`
                );
                console.log(`[UpGames] ✅ ${disponibles.length} items cargados para contexto`);
            } else {
                upgamesContext = '\n\n[CATÁLOGO UPGAMES] La biblioteca está vacía o no hay contenido aprobado en este momento. Informa al usuario honestamente.';
            }
        } catch (ugErr) {
            upgamesContext = '\n\n[CATÁLOGO UPGAMES] No se pudo conectar con UpGames en este momento. Informa al usuario que intente en unos instantes.';
            console.error('[UpGames] Error cargando catálogo:', ugErr.message);
        }
    }

    // ── Selección de cerebro según plan ──────────────────────────
    const useVipBrain = isCreator || isVip || planStatus.plan === 'premium';
    const activeBrain = useVipBrain ? brainVip : brainBase;
    const brainVersion = useVipBrain ? 'ultra' : 'base';
    console.log(`🔀 Cerebro activo: ${brainVersion.toUpperCase()} [${useVipBrain ? 'brain_vip.py' : 'brain.py'}]`);

    try {
        let searchResults = null;
        const skws = ['busca','buscar','encuentra','información sobre','noticias de'];
        if (skws.some(kw=>message.toLowerCase().includes(kw))) {
            const q=message.replace(/^(busca|buscar|encuentra|información sobre|info sobre|noticias de)\s+/i,'').trim();
            searchResults = await searchAll(q);
            searchResults.forEach((r,i)=>{ r._position=i+1; });
        }
        const conversationHistory = Array.isArray(history) ? history.slice(-8) : [];

        // Enriquecer mensaje con contexto UpGames si aplica
        const messageForBrain = upgamesContext
            ? message + upgamesContext
            : message;

        const thought = await activeBrain.process(messageForBrain, conversationHistory, searchResults, userContext);
        const responseText = thought.response||thought.message||'Lo siento, no pude generar una respuesta.';

        if (thought.neural_activity) activeBrain._cachedStats = thought.neural_activity;
        setTimeout(()=>{ activeBrain.learn(message,responseText,true,searchResults||[]).catch(()=>{}); },100);

        if (db) {
            db.collection('messages').insertMany([
                { conversationId:convId, userId, role:'user', content:message, ts:new Date() },
                { conversationId:convId, userId, role:'assistant', content:responseText, neuralActivity:thought.neural_activity, llmUsed:thought.llm_used, ts:new Date() }
            ]).catch(()=>{});
        }

        const msgsToday = planStatus.plan==='free' ? await getMessagesToday(userId) : null;
        res.json({
            message:responseText, conversationId:convId, neuralActivity:thought.neural_activity||{},
            confidence:thought.confidence||0.8, searchPerformed:!!searchResults?.length,
            resultsCount:searchResults?.length||0, intent:thought.intent,
            llmUsed:thought.llm_used||false, llmModel:thought.llm_model||null,
            processingTime:thought.processing_time||null,
            image_url: thought.image_url || null,
            plan:planStatus.plan, messagesUsed:msgsToday, messagesLimit:FREE_MSG_PER_DAY,
            isCreator, brainVersion,
            ts:new Date().toISOString()
        });
    } catch (error) {
        console.error('[/api/chat]',error.message);
        res.status(500).json({ error:'Error procesando mensaje', message:'Hubo un problema. Intenta de nuevo.', conversationId:convId, ts:new Date().toISOString() });
    }
});

app.get('/api/search', async (req, res) => {
    const { q:query } = req.query;
    if (!query) return res.status(400).json({ error:'Query requerido' });
    try {
        const raw=await searchAll(query); raw.forEach((r,i)=>{r._position=i+1;});
        const thought=await brain.process(query,[],raw.length?raw:null);
        if (db) db.collection('searches').insertOne({ query,count:raw.length,ts:new Date() }).catch(()=>{});
        res.json({ query,total:thought.ranked_results?.length||raw.length,results:thought.ranked_results||raw,neuralActivity:thought.neural_activity||{},ts:new Date().toISOString() });
    } catch (error) { res.status(500).json({ error:error.message }); }
});

app.post('/api/click', async (req, res) => {
    const { query,url,position,dwellTime,bounced } = req.body;
    if (!query||!url) return res.status(400).json({ error:'Datos incompletos' });
    try { await brain.click(query,url,position||1,dwellTime||0,bounced); if (db) db.collection('clicks').insertOne({ query,url,position,dwellTime,bounced,ts:new Date() }).catch(()=>{}); res.json({ ok:true }); }
    catch (error) { res.status(500).json({ error:error.message }); }
});

app.post('/api/feedback', async (req, res) => {
    const { message,response,helpful } = req.body;
    if (!message) return res.status(400).json({ error:'Datos incompletos' });
    try { await brain.learn(message,response||'',helpful!==false); res.json({ ok:true }); }
    catch (error) { res.status(500).json({ error:error.message }); }
});


// ══════════════════════════════════════════════════════════════════
//  INTEGRACIÓN UPGAMES — NEXUS ve la página en tiempo real
// ══════════════════════════════════════════════════════════════════

/**
 * POST /api/upgames/evento
 * UpGames envía eventos de comportamiento del usuario aquí.
 * Tipos: search | view | download | favorite | unfavorite | category
 */
app.post('/api/upgames/evento', async (req, res) => {
    const { usuario, tipo, datos, ts } = req.body;
    if (!usuario || !tipo) return res.status(400).json({ error: 'usuario y tipo son requeridos' });
    const tiposValidos = ['search','view','download','favorite','unfavorite','category'];
    if (!tiposValidos.includes(tipo)) return res.status(400).json({ error: 'tipo de evento invalido' });
    const evento = { usuario, tipo, datos: datos || {}, ts: ts ? new Date(ts) : new Date() };
    if (db) {
        try {
            await db.collection('upgames_eventos').insertOne(evento);
            db.collection('upgames_eventos').createIndex({ usuario: 1, ts: -1 }).catch(()=>{});
            db.collection('upgames_eventos').createIndex({ tipo: 1, ts: -1 }).catch(()=>{});
            db.collection('upgames_eventos').createIndex({ ts: 1 },{ expireAfterSeconds: 60*60*24*90 }).catch(()=>{});
        } catch(e) { console.error('[upgames/evento]', e.message); }
    }
    if (tipo === 'search' && datos?.query) {
        brainBase.learn(`El usuario buscó en UpGames: "${datos.query}"`, 'Registrado en perfil', true, []).catch(()=>{});
    }
    res.json({ ok: true });
});

/**
 * GET /api/upgames/perfil/:usuario
 * Perfil de gustos calculado desde eventos. Usado por UpGames para reordenar el feed.
 */
app.get('/api/upgames/perfil/:usuario', async (req, res) => {
    const { usuario } = req.params;
    if (!usuario) return res.status(400).json({ error: 'usuario requerido' });
    if (!db) return res.json({ categorias: [], tags: [], recientes: [], totalEventos: 0 });
    try {
        const desde = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);
        const eventos = await db.collection('upgames_eventos')
            .find({ usuario, ts: { $gte: desde } })
            .sort({ ts: -1 }).limit(500).toArray();
        if (!eventos.length) return res.json({ categorias: [], tags: [], recientes: [], totalEventos: 0 });

        const PESOS = { download: 10, favorite: 8, view: 3, search: 2, category: 5, unfavorite: -4 };
        const catMap = {};
        const tagMap = {};
        const recientes = [];

        for (const ev of eventos) {
            const peso = PESOS[ev.tipo] || 1;
            const d = ev.datos || {};
            if (d.category) catMap[d.category] = (catMap[d.category] || 0) + peso;
            if (Array.isArray(d.tags)) d.tags.forEach(t => { if(t) tagMap[t] = (tagMap[t]||0)+1; });
            if (recientes.length < 20 && d.itemId) recientes.push({ itemId: d.itemId, title: d.title||'', tipo: ev.tipo, ts: ev.ts });
        }

        const categorias = Object.entries(catMap).map(([nombre, peso]) => ({ nombre, peso })).sort((a,b)=>b.peso-a.peso);
        const tags = Object.entries(tagMap).map(([tag, count]) => ({ tag, count })).sort((a,b)=>b.count-a.count).slice(0,20);
        res.json({ usuario, categorias, tags, recientes, totalEventos: eventos.length });
    } catch(e) { console.error('[upgames/perfil]', e.message); res.status(500).json({ error: 'Error calculando perfil' }); }
});

/**
 * GET /api/proactive
 * NEXUS genera espontáneamente el primer mensaje de la sesión.
 * Usa el estado PAD actual del brain, la hora, y la memoria del usuario.
 * Se llama desde UpGames al abrir el panel NEXUS (una vez por sesión de pestaña).
 */
app.get('/api/proactive', requireAuth, async (req, res) => {
    try {
        const { ObjectId } = require('mongodb');
        const user = db ? await db.collection('users').findOne({ _id: new ObjectId(req.user.id) }) : null;
        const userEmail   = user?.email || req.user.email || '';
        const isCreator   = isCreatorAccount(userEmail);
        const isVip       = user?.isVip || isVipAccount(userEmail);
        const useVipBrain = isCreator || isVip || (user?.plan === 'premium');
        const activeBrain = useVipBrain ? brainVip : brainBase;

        if (!activeBrain.ready) {
            return res.json({ message: '...', proactive: true, mode: 'neutral' });
        }

        const userCtx = {
            userId:      req.user.id,
            username:    user?.username    || '',
            displayName: user?.displayName || user?.username || '',
            email:       userEmail,
            isCreator,
            isVip,
            plan:        user?.plan || 'free',
        };

        const result = await activeBrain.proactive(userCtx);
        res.json({
            message:  result.message || result.response || '...',
            mode:     result.mode    || 'neutral',
            pad:      result.pad     || [0, 0, 0],
            proactive: true,
        });
    } catch (err) {
        console.error('[/api/proactive]', err.message);
        res.json({ message: '...', proactive: true, mode: 'neutral' });
    }
});

/**
 * POST /api/upgames/recomendar
 * NEXUS calcula recomendaciones reales desde el perfil + llama al backend de UpGames.
 */
app.post('/api/upgames/recomendar', requireAuth, async (req, res) => {
    const { usuario, mensaje } = req.body;
    if (!usuario) return res.status(400).json({ error: 'usuario requerido' });
    const UPGAMES_API = process.env.UPGAMES_API_URL || 'https://upgames-production.up.railway.app';
    try {
        // 1. Calcular perfil del usuario
        let perfil = { categorias: [], tags: [], recientes: [] };
        if (db) {
            const desde = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);
            const eventos = await db.collection('upgames_eventos')
                .find({ usuario, ts: { $gte: desde } }).sort({ ts: -1 }).limit(300).toArray();
            const PESOS = { download: 10, favorite: 8, view: 3, search: 2, category: 5 };
            const catMap = {}; const tagMap = {};
            for (const ev of eventos) {
                const peso = PESOS[ev.tipo] || 1;
                const d = ev.datos || {};
                if (d.category) catMap[d.category] = (catMap[d.category]||0) + peso;
                if (Array.isArray(d.tags)) d.tags.forEach(t => { if(t) tagMap[t] = (tagMap[t]||0)+1; });
            }
            perfil.categorias = Object.entries(catMap).map(([n,p])=>({nombre:n,peso:p})).sort((a,b)=>b.peso-a.peso);
            perfil.tags = Object.entries(tagMap).map(([t,c])=>({tag:t,count:c})).sort((a,b)=>b.count-a.count);
            perfil.recientes = eventos.filter(e=>e.datos?.itemId).slice(0,10).map(e=>e.datos.itemId);
        }

        // 2. Llamar a UpGames con el perfil
        const params = new URLSearchParams();
        const catQuery = perfil.categorias.slice(0,4).map(c=>`${c.nombre}:${c.peso}`).join(',');
        const tagQuery = perfil.tags.slice(0,8).map(t=>t.tag).join(',');
        const excluirQuery = perfil.recientes.slice(0,15).join(',');
        if (catQuery)    params.set('categorias', catQuery);
        if (tagQuery)    params.set('tags', tagQuery);
        if (excluirQuery) params.set('excluir', excluirQuery);
        params.set('limite', '8');

        const url = `${UPGAMES_API}/items/recomendados/${encodeURIComponent(usuario)}?${params.toString()}`;
        let items = [];
        try {
            const resp = await axios.get(url, { timeout: 8000 });
            items = resp.data?.items || (Array.isArray(resp.data) ? resp.data : []);
        } catch (primaryErr) {
            console.warn('[upgames/recomendar] endpoint personalizado falló:', primaryErr.message, '— usando fallback /items');
            try {
                const fallback = await axios.get(`${UPGAMES_API}/items`, { timeout: 8000 });
                const all = Array.isArray(fallback.data) ? fallback.data : [];
                // Filtrar aprobados y no-caídos, ordenar por categoría preferida del perfil
                const catPref = new Set(perfil.categorias.map(c => c.nombre));
                items = all
                    .filter(i => i.status === 'aprobado' && i.linkStatus !== 'caido')
                    .sort((a, b) => {
                        const aMatch = catPref.has(a.category) ? 1 : 0;
                        const bMatch = catPref.has(b.category) ? 1 : 0;
                        if (bMatch !== aMatch) return bMatch - aMatch;
                        return (b.descargasEfectivas || 0) - (a.descargasEfectivas || 0);
                    })
                    .slice(0, 10);
                console.log(`[upgames/recomendar] fallback OK — ${items.length} items`);
            } catch (fallbackErr) {
                console.error('[upgames/recomendar] fallback también falló:', fallbackErr.message);
            }
        }

        // 3. Respuesta natural del brain si hay mensaje
        let respuestaNatural = null;
        if (mensaje && items.length > 0) {
            const contextoItems = items.map(i=>`- "${i.title}" (${i.category}) — ${i.descargasEfectivas||0} descargas`).join('\n');
            const thought = await brainVip.process(mensaje, [], null, {
                upgames_context: true,
                items_disponibles: contextoItems,
                perfil_usuario: {
                    categorias_favoritas: perfil.categorias.slice(0,3).map(c=>c.nombre),
                    tags_favoritos: perfil.tags.slice(0,5).map(t=>t.tag)
                }
            });
            respuestaNatural = thought.response || thought.message || null;
        }

        res.json({
            ok: true, items,
            perfil: { categoriasFavoritas: perfil.categorias.slice(0,3), tagsFavoritos: perfil.tags.slice(0,5) },
            respuestaNatural
        });
    } catch(e) {
        console.error('[upgames/recomendar]', e.message);
        res.status(500).json({ error: 'Error obteniendo recomendaciones' });
    }
});

app.get('/api/stats', async (req, res) => {
    try {
        const neural = await brainBase.getStats();
        let dbStats={};
        if (db) {
            try {
                const [msgs,clicks,searches,users,premiumUsers] = await Promise.all([
                    db.collection('messages').countDocuments(),
                    db.collection('clicks').countDocuments(),
                    db.collection('searches').countDocuments(),
                    db.collection('users').countDocuments(),
                    db.collection('users').countDocuments({ plan:'premium' })
                ]);
                dbStats={ messages:msgs,clicks,searches,users,premiumUsers };
            } catch (_) {}
        }
        res.json({
            neural, db:dbStats,
            server:{
                uptime:Math.round(process.uptime()),
                restarts:brainBase.restarts,
                restartsVip:brainVip.restarts,
                port:PORT,
                brainReady:brainBase.ready,
                brainVipReady:brainVip.ready
            }
        });
    } catch (error) {
        if (brainBase._cachedStats) return res.json({ neural:brainBase._cachedStats,db:{},server:{ uptime:Math.round(process.uptime()),restarts:brainBase.restarts,port:PORT,brainReady:brainBase.ready },cached:true });
        res.status(500).json({ error:error.message });
    }
});

app.get('/health', (req, res) => {
    res.json({ status:brainBase.ready?'ok':'initializing',brainReady:brainBase.ready,brainVipReady:brainVip.ready,db:db!==null,restarts:brainBase.restarts,restartsVip:brainVip.restarts,uptime:process.uptime(),ts:new Date().toISOString() });
});

// ══════════════════════════════════════════════════════════════════
//  UTILIDADES DE ARCHIVO — extracción de contenido
// ══════════════════════════════════════════════════════════════════

async function extractFileContent(filePath, mimeType, originalName) {
    const ext = path.extname(originalName).toLowerCase();
    try {
        // Imágenes → base64 para enviar al LLM
        if (mimeType?.startsWith('image/') || ['.jpg','.jpeg','.png','.gif','.webp','.svg'].includes(ext)) {
            const buf = await fs.readFile(filePath);
            const b64 = buf.toString('base64');
            let meta = { width: 0, height: 0, format: ext.slice(1) };
            if (sharp) { try { meta = await sharp(buf).metadata(); } catch(e){} }
            return {
                type: 'image',
                base64: b64,
                mimeType: mimeType || `image/${ext.slice(1)}`,
                meta,
                textSummary: `[Imagen adjunta: ${originalName}, ${meta.width}x${meta.height} ${meta.format}]`
            };
        }
        // PDF → texto
        if (mimeType === 'application/pdf' || ext === '.pdf') {
            if (pdfParse) {
                const buf = await fs.readFile(filePath);
                const result = await pdfParse(buf);
                return { type: 'pdf', text: result.text, pages: result.numpages, textSummary: `[PDF: ${originalName}, ${result.numpages} páginas]\n\n${result.text.slice(0, 50000)}` };
            }
            return { type: 'pdf', text: '[PDF — instala pdf-parse para extracción de texto]', textSummary: `[PDF adjunto: ${originalName}]` };
        }
        // DOCX → texto
        if (['.docx','.doc'].includes(ext) || mimeType?.includes('wordprocessingml')) {
            if (mammoth) {
                const buf = await fs.readFile(filePath);
                const result = await mammoth.extractRawText({ buffer: buf });
                return { type: 'docx', text: result.value, textSummary: `[Documento Word: ${originalName}]\n\n${result.value.slice(0, 50000)}` };
            }
            return { type: 'docx', text: '[DOCX — instala mammoth para extracción]', textSummary: `[DOCX adjunto: ${originalName}]` };
        }
        // Texto plano, código, etc.
        const textExts = ['.txt','.md','.js','.ts','.jsx','.tsx','.py','.cpp','.c','.h','.cs',
                          '.java','.go','.rs','.php','.rb','.swift','.kt','.sh','.bash','.sql',
                          '.yaml','.yml','.toml','.env','.html','.css','.json','.xml','.csv','.log'];
        if (textExts.includes(ext) || mimeType?.startsWith('text/') || mimeType === 'application/json') {
            const text = await fs.readFile(filePath, 'utf-8');
            return { type: 'code', ext: ext.slice(1), text, textSummary: `[Archivo ${originalName} — ${text.split('\n').length} líneas]\n\n${text}` };
        }
        return { type: 'binary', textSummary: `[Archivo binario adjunto: ${originalName}]` };
    } catch (e) {
        return { type: 'error', textSummary: `[Error leyendo ${originalName}: ${e.message}]` };
    }
}

// ── POST /api/upload — subir archivo y procesar ────────────────────
app.post('/api/upload', requireAuth, (req, res) => {
    if (!upload) return res.status(501).json({ error: 'Módulo multer no instalado. Ejecuta: npm install multer' });
    const uploader = upload.single('file');
    uploader(req, res, async (err) => {
        if (err) return res.status(400).json({ error: err.message });
        if (!req.file) return res.status(400).json({ error: 'No se recibió ningún archivo' });

        try {
            const { path: filePath, mimetype, originalname, size } = req.file;
            const content = await extractFileContent(filePath, mimetype, originalname);

            // Si es imagen, generar thumbnail si sharp disponible
            let thumbBase64 = null;
            if (content.type === 'image' && sharp) {
                try {
                    const thumbBuf = await sharp(filePath).resize(400, 400, { fit: 'inside' }).jpeg({ quality: 80 }).toBuffer();
                    thumbBase64 = thumbBuf.toString('base64');
                } catch(e) {}
            }

            // Limpiar archivo temporal
            fs.unlink(filePath).catch(() => {});

            console.log(`📎 [upload] ${originalname} (${(size/1024).toFixed(1)}KB) → tipo: ${content.type}`);
            res.json({
                ok: true,
                type: content.type,
                name: originalname,
                size,
                mimeType: mimetype,
                base64: content.base64 || null,
                thumbBase64,
                text: content.text || null,          // texto completo SIN truncar
                textSummary: content.textSummary,
                meta: content.meta || null,
                pages: content.pages || null,
                ext: content.ext || null,
                lines: content.text ? content.text.split('\n').length : null
            });
        } catch (e) {
            console.error('[upload]', e.message);
            res.status(500).json({ error: `Error procesando archivo: ${e.message}` });
        }
    });
});

// ── POST /api/chat-with-file — chat enviando archivos ──────────────
app.post('/api/chat-with-file', requireAuth, async (req, res) => {
    if (!checkRateLimit(req, res, 60, 60000)) return;
    const { message, conversationId, history, fileData, fileData2 } = req.body;

    const userId = req.user.id;
    const { ObjectId } = require('mongodb');
    const user = db ? await db.collection('users').findOne({ _id: new ObjectId(userId) }) : null;
    const planStatus = user ? await getPlanStatus(user) : { plan: 'free' };

    // ℹ️ Sin límite de mensajes en plan free

    const userEmail = user?.email || req.user.email || '';
    const isCreator = isCreatorAccount(userEmail);
    const isVip     = user?.isVip || isVipAccount(userEmail);
    const useVipBrain = isCreator || isVip || planStatus.plan === 'premium';
    const activeBrain = useVipBrain ? brainVip : brainBase;

    // Construir el mensaje enriquecido con el/los archivos
    const isComparison = !!(fileData && fileData2);
    let enrichedMessage = message || '';
    if (isComparison) {
        const defaultQ = fileData.type === 'image'
            ? `Compara estas dos imágenes: ${fileData.name} vs ${fileData2.name}. ¿Cuál es mejor y por qué?`
            : `Compara estos dos archivos en todos los aspectos: ${fileData.name} vs ${fileData2.name}. ¿Cuál es mejor y por qué?`;
        enrichedMessage = message || defaultQ;
    } else if (fileData) {
        if (fileData.type === 'image') {
            enrichedMessage = message || 'Analiza esta imagen y describe todo lo que ves.';
        } else {
            enrichedMessage = message || 'Analiza este archivo y responde.';
        }
    }

    const userContext = {
        userId, email: userEmail,
        username: user?.username || req.user.username || '',
        displayName: user?.displayName || user?.username || '',
        // Archivo 2 para comparación
        fileData2: fileData2 ? {
            type:     fileData2.type,
            name:     fileData2.name,
            content:  fileData2.type !== 'image' ? (fileData2.text || '') : '',
            base64:   fileData2.type === 'image'  ? (fileData2.base64 || null) : null,
            mimeType: fileData2.mimeType || null,
        } : null,
        plan: planStatus.plan, isVip, isCreator,
        hasFile: !!fileData,
        fileType: fileData?.type || null,
        fileName: fileData?.name || null,
        // Pasar base64 de imagen directamente al brain para visión
        image_base64:  (fileData?.type === 'image') ? (fileData?.base64 || null) : null,
        image_mimeType: (fileData?.type === 'image') ? (fileData?.mimeType || 'image/jpeg') : null,
        // Pasar contenido completo de archivos de código/texto
        fileContent: (fileData?.type !== 'image') ? (fileData?.text || '') : '',
    };

    try {
        const conversationHistory = Array.isArray(history) ? history.slice(-8) : [];
        const convId = conversationId || `conv_${Date.now()}`;
        const thought = await activeBrain.process(enrichedMessage, conversationHistory, null, userContext);
        const responseText = thought.response || thought.message || 'Lo siento, no pude procesar el archivo.';
        const imageUrl = thought.image_url || null;
        const fileOutput = thought.file_content || null;
        const fileOutputName = thought.file_name || fileData?.name || 'archivo_modificado.txt';
        const fileOutputLines = thought.file_lines || 0;

        // Si hay archivo generado, guardarlo en disco para descarga
        let downloadUrl = null;
        if (fileOutput) {
            try {
                const safeName = fileOutputName.replace(/[^a-zA-Z0-9._-]/g, '_');
                const outPath  = path.join(GENERATED_DIR, safeName);
                await fs.writeFile(outPath, fileOutput, 'utf-8');
                downloadUrl = `/generated/${safeName}`;
                console.log(`📁 [file-output] ${safeName} (${fileOutputLines} líneas) → ${downloadUrl}`);
                // Auto-limpiar después de 2 horas
                setTimeout(() => fs.unlink(outPath).catch(() => {}), 2 * 60 * 60 * 1000);
            } catch(e) {
                console.error('[file-save]', e.message);
            }
        }

        setTimeout(() => { activeBrain.learn(enrichedMessage, responseText, true, []).catch(() => {}); }, 100);

        if (db) {
            db.collection('messages').insertMany([
                { conversationId: convId, userId, role: 'user', content: message || '[Archivo adjunto]', hasFile: !!fileData, fileName: fileData?.name, ts: new Date() },
                { conversationId: convId, userId, role: 'assistant', content: responseText, ts: new Date() }
            ]).catch(() => {});
        }

        res.json({
            message: responseText,
            image_url: imageUrl,
            file_output: fileOutput ? true : false,
            file_name: fileOutputName,
            file_lines: fileOutputLines,
            download_url: downloadUrl,
            conversationId: convId,
            plan: planStatus.plan,
            ts: new Date().toISOString()
        });
    } catch (e) {
        console.error('[chat-with-file]', e.message);
        res.status(500).json({ error: 'Error procesando archivo con el cerebro' });
    }
});

// ══════════════════════════════════════════════════════════════════
//  GENERACIÓN DE ARCHIVOS (código, docs, etc.) — SIN LÍMITE
// ══════════════════════════════════════════════════════════════════

// ── Helper: llama directamente a Anthropic o Groq para CodeGen ─────────────
// Bypasa el brain Python — genera código puro de alta calidad sin filtros de chat
async function codegenLLMCall(systemPrompt, userPrompt, maxTokens = 12000) {
    const https          = require('https');
    const anthropicKey   = process.env.ANTHROPIC_API_KEY;
    const groqKey        = process.env.GROQ_API_KEY;

    function httpsPost(hostname, path, headers, body, timeoutMs) {
        return new Promise((resolve, reject) => {
            const req = https.request({ hostname, path, method: 'POST', headers, timeout: timeoutMs },
                (res) => { let d = ''; res.on('data', c => d += c); res.on('end', () => resolve({ status: res.statusCode, data: d })); }
            );
            req.on('error', reject);
            req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
            req.write(body); req.end();
        });
    }

    // 1. Anthropic Claude Sonnet — mejor calidad para CodeGen
    if (anthropicKey) {
        try {
            const body = JSON.stringify({
                model: 'claude-sonnet-4-5', max_tokens: maxTokens, temperature: 0.2,
                system: systemPrompt,
                messages: [{ role: 'user', content: userPrompt }]
            });
            const resp = await httpsPost('api.anthropic.com', '/v1/messages', {
                'Content-Type': 'application/json',
                'x-api-key': anthropicKey,
                'anthropic-version': '2023-06-01',
                'Content-Length': Buffer.byteLength(body)
            }, body, 300000);
            if (resp.status === 200) {
                const parsed = JSON.parse(resp.data);
                const text   = (parsed.content || []).filter(b => b.type === 'text').map(b => b.text).join('');
                if (text && text.trim()) { console.log(`[CodeGen] Claude OK — ${text.length} chars`); return text.trim(); }
            } else { console.warn(`[CodeGen] Anthropic HTTP ${resp.status}: ${resp.data.slice(0,150)}`); }
        } catch(e) { console.warn(`[CodeGen] Anthropic error: ${e.message}`); }
    }

    // 2. Fallback: Groq
    if (groqKey) {
        try {
            const body = JSON.stringify({
                model: 'llama-3.3-70b-versatile',
                max_tokens: Math.min(maxTokens, 8000),
                temperature: 0.2,
                messages: [{ role: 'system', content: systemPrompt }, { role: 'user', content: userPrompt }]
            });
            const resp = await httpsPost('api.groq.com', '/openai/v1/chat/completions', {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${groqKey}`,
                'Content-Length': Buffer.byteLength(body)
            }, body, 120000);
            if (resp.status === 200) {
                const text = JSON.parse(resp.data).choices?.[0]?.message?.content || '';
                if (text && text.trim()) { console.log(`[CodeGen] Groq OK — ${text.length} chars`); return text.trim(); }
            } else { console.warn(`[CodeGen] Groq HTTP ${resp.status}: ${resp.data.slice(0,150)}`); }
        } catch(e) { console.warn(`[CodeGen] Groq error: ${e.message}`); }
    }

    console.error('[CodeGen] Todos los proveedores fallaron — configura ANTHROPIC_API_KEY o GROQ_API_KEY');
    return null;
}

// ── Helper: limpia bloques markdown del contenido generado ──────────────────
function cleanCodeOutput(text) {
    if (!text) return '';
    const single = text.match(/^```[\w]*\n?([\s\S]*?)\n?```\s*$/);
    if (single) return single[1].trim();
    const blocks = [...text.matchAll(/```[\w]*\n?([\s\S]*?)\n?```/g)].map(b => b[1]);
    if (blocks.length > 0) return blocks.sort((a, b) => b.length - a.length)[0].trim();
    return text.trim();
}

const SYS_CODEGEN = `Eres NEXUS, un experto generador de código creado por Jhonatan David Castro Galviz.
REGLAS ABSOLUTAS — NUNCA ROMPER:
1. Genera ÚNICAMENTE el contenido del archivo solicitado. Código puro, completo y funcional.
2. NUNCA uses bloques markdown (\`\`\`). Solo el contenido del archivo, sin envoltorios.
3. NUNCA pongas explicaciones, comentarios meta, ni texto fuera del código.
4. NUNCA uses TODOs, placeholders, ni comentarios como "// agregar aquí".
5. El archivo debe funcionar TAL COMO SE GENERA, sin ninguna modificación.
6. Si es HTML: incluye DOCTYPE, head completo, body completo, CSS y JS necesarios.
7. Si es JS/Python/etc: código real y completo, no esqueletos ni stubs.
8. Longitud: genera tanto código como sea necesario para que el archivo sea COMPLETO.`;

// POST /api/generate-project — genera proyecto completo multi-archivo
app.post('/api/generate-project', requireAuth, async (req, res) => {
    if (!checkRateLimit(req, res, 10, 60000)) return;
    const { prompt, category, projectName } = req.body;
    if (!prompt) return res.status(400).json({ error: 'Se requiere descripción del proyecto' });

    const userId = req.user.id;
    const { ObjectId } = require('mongodb');
    const user = db ? await db.collection('users').findOne({ _id: new ObjectId(userId) }) : null;
    const planStatus = user ? await getPlanStatus(user) : { plan: 'free' };
    const userEmail = user?.email || req.user.email || '';
    const isCreator = isCreatorAccount(userEmail);
    const isVip     = user?.isVip || isVipAccount(userEmail);
    const useVipBrain = isCreator || isVip || planStatus.plan === 'premium';

    if (!useVipBrain) {
        const genToday = await getFreeGenToday(userId);
        if (genToday >= FREE_GEN_PER_DAY) {
            return res.status(429).json({
                error: `Límite de ${FREE_GEN_PER_DAY} generaciones por día del plan gratuito alcanzado. Se renueva a medianoche. Actualiza a Ultra para proyectos ilimitados.`,
                limitReached: true, genUsed: genToday, genLimit: FREE_GEN_PER_DAY
            });
        }
        await incrementFreeGen(userId);
        console.log(`[Free] generate-project — ${genToday + 1}/${FREE_GEN_PER_DAY} usos hoy (user: ${userId})`);
    }

    const FILE_MAPS = {
        web:       ['index.html','style.css','script.js'],
        game:      ['index.html','game.js','style.css'],
        app:       ['App.jsx','styles.css','logic.js','README.md'],
        software:  ['main.py','utils.py','config.json','README.md'],
        api:       ['server.js','routes.js','middleware.js','package.json'],
        bot:       ['bot.js','commands.js','config.json','.env.example'],
        emulator:  ['index.html','cpu.js','memory.js','display.js'],
        tool:      ['index.html','tool.js','style.css','README.md'],
        dashboard: ['index.html','dashboard.js','charts.js','style.css'],
        extension: ['manifest.json','popup.html','popup.js','background.js','style.css'],
    };

    const MAX_PROJECT_FILES = useVipBrain ? 10 : 3;
    const cat       = category || 'web';
    const baseFiles = (FILE_MAPS[cat] || FILE_MAPS['web']).slice(0, MAX_PROJECT_FILES);
    const pName     = projectName || 'mi_proyecto';

    console.log(`🚀 [generate-project] cat:${cat} name:${pName} plan:${planStatus.plan} prompt:${prompt.slice(0,80)}`);

    try {
        // Paso 1: decidir estructura de archivos
        const planSys  = `Eres un arquitecto de software. Responde ÚNICAMENTE con JSON válido, sin markdown ni explicaciones.`;
        const planUser = `Proyecto:\nCATEGORÍA: ${cat}\nNOMBRE: ${pName}\nDESCRIPCIÓN: ${prompt}\nSUGERIDOS: ${baseFiles.join(', ')}\nMÁXIMO: ${MAX_PROJECT_FILES} archivos\n\nResponde solo: {"files": ["archivo1.ext", "archivo2.ext"]}`;

        let fileList = baseFiles;
        const planRaw = await codegenLLMCall(planSys, planUser, 200);
        if (planRaw) {
            try {
                const m = planRaw.match(/\{[\s\S]*\}/);
                if (m) {
                    const p = JSON.parse(m[0]);
                    if (Array.isArray(p.files) && p.files.length > 0) fileList = p.files.slice(0, MAX_PROJECT_FILES);
                }
            } catch(e) { /* usar lista base */ }
        }
        console.log(`[generate-project] Archivos: ${fileList.join(', ')}`);

        // Paso 2: generar cada archivo completo — directo al LLM
        const generatedFiles = [];
        for (const fileName of fileList) {
            const done = generatedFiles.map(f => f.name).join(', ') || 'ninguno';
            const userMsg = `PROYECTO: "${pName}" (${cat})
DESCRIPCIÓN: ${prompt}
TODOS LOS ARCHIVOS: ${fileList.join(', ')}
YA GENERADOS: ${done}

GENERA AHORA EL ARCHIVO: ${fileName}
Código completo y funcional. Sin markdown. Sin explicaciones. Solo el contenido del archivo.`;

            const raw     = await codegenLLMCall(SYS_CODEGEN, userMsg, 12000);
            let content   = cleanCodeOutput(raw || '');

            if (!content || content.length < 10) {
                content = `/* NEXUS CodeGen: Error generando ${fileName}. Reintenta con descripción más detallada. */`;
                console.error(`[generate-project] ⚠️ Sin contenido para ${fileName}`);
            }

            let downloadUrl = null;
            try {
                const safeName = `${pName}_${fileName}`.replace(/[^a-zA-Z0-9._-]/g, '_');
                const outPath  = path.join(GENERATED_DIR, safeName);
                await fs.writeFile(outPath, content, 'utf-8');
                downloadUrl = `/generated/${safeName}`;
                setTimeout(() => fs.unlink(outPath).catch(() => {}), 2 * 60 * 60 * 1000);
            } catch(e) { console.error('[generate-project] save error:', e.message); }

            generatedFiles.push({ name: fileName, content, downloadUrl, lines: content.split('\n').length });
            console.log(`[generate-project] ✓ ${fileName} — ${content.split('\n').length} líneas`);
        }

        res.json({
            ok: true, category: cat, projectName: pName,
            files: generatedFiles, totalFiles: generatedFiles.length,
            genUsed: useVipBrain ? null : await getFreeGenToday(userId), genLimit: useVipBrain ? null : FREE_GEN_PER_DAY,
            ts: new Date().toISOString()
        });

    } catch(e) {
        console.error('[generate-project]', e.message);
        res.status(500).json({ error: `Error generando proyecto: ${e.message}` });
    }
});

// POST /api/generate-file — genera / edita / corrige / analiza un archivo
app.post('/api/generate-file', requireAuth, async (req, res) => {
    if (!checkRateLimit(req, res, 20, 60000)) return;
    const { prompt, fileType, fileName, currentContent, operation } = req.body;
    if (!prompt && !currentContent) return res.status(400).json({ error: 'Se requiere prompt o contenido' });

    const userId = req.user.id;
    const { ObjectId } = require('mongodb');
    const user = db ? await db.collection('users').findOne({ _id: new ObjectId(userId) }) : null;
    const planStatus = user ? await getPlanStatus(user) : { plan: 'free' };
    const userEmail = user?.email || req.user.email || '';
    const isCreator = isCreatorAccount(userEmail);
    const isVip     = user?.isVip || isVipAccount(userEmail);
    const useVipBrain = isCreator || isVip || planStatus.plan === 'premium';

    if (!useVipBrain) {
        const genToday = await getFreeGenToday(userId);
        if (genToday >= FREE_GEN_PER_DAY) {
            return res.status(429).json({
                error: `Límite de ${FREE_GEN_PER_DAY} archivos/imágenes por día del plan gratuito alcanzado. Se renueva a medianoche. Actualiza a Ultra para generaciones ilimitadas.`,
                limitReached: true, genUsed: genToday, genLimit: FREE_GEN_PER_DAY
            });
        }
        await incrementFreeGen(userId);
        console.log(`[Free] generate-file — ${genToday + 1}/${FREE_GEN_PER_DAY} usos hoy (user: ${userId})`);
    }

    const op = operation || 'create';
    let systemPrompt, userPrompt;

    if (op === 'analyze' && currentContent) {
        systemPrompt = `Eres NEXUS, experto analista de código creado por Jhonatan David Castro Galviz. Analiza código con detalle técnico. Responde en español de forma clara y estructurada.`;
        userPrompt   = `Analiza este archivo (${fileName || 'archivo'}, ${currentContent.split('\n').length} líneas):\nPREGUNTA: ${prompt}\n\nCÓDIGO:\n${currentContent}`;
    } else if ((op === 'edit' || op === 'fix') && currentContent) {
        const opLabel = op === 'fix' ? 'CORRIGE ERRORES EN' : 'EDITA';
        systemPrompt = SYS_CODEGEN;
        userPrompt   = `${opLabel} ESTE ARCHIVO: ${fileName || 'archivo'}
INSTRUCCIÓN: ${prompt}

CONTENIDO ACTUAL (${currentContent.split('\n').length} líneas):
${currentContent}

Devuelve el archivo completo con los cambios aplicados. Sin markdown. Sin explicaciones. Solo el código.`;
    } else {
        systemPrompt = SYS_CODEGEN;
        userPrompt   = `GENERA EL ARCHIVO: ${fileName || `archivo.${fileType || 'txt'}`}
TIPO: ${fileType || 'texto'}
REQUISITOS: ${prompt}

Genera el contenido completo del archivo. Sin markdown. Sin explicaciones. Solo el contenido.`;
    }

    try {
        console.log(`📝 [generate-file] op:${op} tipo:${fileType} file:${fileName} prompt:${prompt?.slice(0,60)}`);

        const maxTok = op === 'analyze' ? 4000 : 12000;
        const raw    = await codegenLLMCall(systemPrompt, userPrompt, maxTok);

        let content;
        if (op === 'analyze') {
            content = raw || 'No se pudo analizar el archivo en este momento.';
        } else {
            content = cleanCodeOutput(raw || '');
            if (!content || content.length < 5) {
                content = `/* NEXUS CodeGen: Error generando ${fileName || 'archivo'}. Reintenta. */`;
                console.error(`[generate-file] ⚠️ Sin contenido`);
            }
        }

        let savedFileName = null;
        let downloadUrl   = null;
        if (op !== 'analyze') {
            const safeName = (fileName || `nexus_${Date.now()}.${fileType || 'txt'}`).replace(/[^a-zA-Z0-9._-]/g, '_');
            const outPath  = path.join(GENERATED_DIR, safeName);
            await fs.writeFile(outPath, content, 'utf-8');
            savedFileName = safeName;
            downloadUrl   = `/generated/${safeName}`;
            setTimeout(async () => {
                try {
                    const files = await fs.readdir(GENERATED_DIR);
                    const now   = Date.now();
                    for (const f of files) {
                        const fp = path.join(GENERATED_DIR, f);
                        const st = await fs.stat(fp);
                        if (now - st.mtimeMs > 60 * 60 * 1000) await fs.unlink(fp).catch(() => {});
                    }
                } catch(e) {}
            }, 5000);
        }

        res.json({
            ok: true, operation: op, fileType, fileName,
            content, savedFileName, downloadUrl,
            lines: content.split('\n').length,
            chars: content.length,
            ts: new Date().toISOString()
        });
    } catch (e) {
        console.error('[generate-file]', e.message);
        res.status(500).json({ error: `Error generando archivo: ${e.message}` });
    }
});

// GET /api/generated/:filename — descargar archivo generado
app.get('/api/generated/:filename', requireAuth, async (req, res) => {
    const safeName = req.params.filename.replace(/[^a-zA-Z0-9._-]/g, '_');
    const filePath = path.join(GENERATED_DIR, safeName);
    try {
        await fs.access(filePath);
        res.download(filePath, safeName);
    } catch (e) {
        res.status(404).json({ error: 'Archivo no encontrado o expirado' });
    }
});

// ══════════════════════════════════════════════════════════════════
//  INICIO
// ══════════════════════════════════════════════════════════════════
async function start() {
    await connectDB();
    for (const d of ['models','data','logs','cache','uploads_tmp','generated']) await fs.mkdir(path.join(__dirname, d), { recursive:true });

    app.listen(PORT, '0.0.0.0', () => {
        console.log(`
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   🧠  NEXUS v8.0 — Multimodal + CodeGen + Anti-Fraude + VIP     ║
║                                                                  ║
║   🌐  http://localhost:${PORT.toString().padEnd(47)}║
║   💳  PayPal $${PLAN_PRICE}/mes · Reset automático a medianoche        ║
║   🆓  Free: ${FREE_MSG_PER_DAY} msgs/día · 👑 VIP: ${VIP_ACCOUNTS.length} cuentas permanentes    ║
║   📎  Upload: imágenes, PDF, DOCX, código (50MB max)            ║
║   📝  CodeGen: genera archivos sin límite de tamaño             ║
║   🛡️   Anti-fraude: brute-force, IP flood, tx duplicada,         ║
║       payer blacklist, multi-account, fake tx pattern           ║
║                                                                  ║
║   Creado por: Jhonatan David Castro Galvis                       ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝`);

        const SELF_PING_URL = process.env.SELF_PING_URL;
        if (SELF_PING_URL) {
            const ping = async () => { try { await axios.get(`${SELF_PING_URL.replace(/\/$/,'')}/health`,{ timeout:10000 }); } catch {} };
            setTimeout(ping, 30000);
            setInterval(ping, 14 * 60 * 1000);
        }
    });
}

start().catch(err => { console.error('❌ Error al iniciar:', err); process.exit(1); });
module.exports = app;
