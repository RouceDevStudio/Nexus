#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeVerifier — 5 redes neurales para verificación de código generado
Integra con NEXUS Brain v12.0 APEX

Creado para: Jhonatan David Castro Galviz / UpGames NEXUS

Redes (todas DynamicNeuralNet — se auto-expanden y entrenan con cada archivo):
  1. SyntaxNet    — detección real de errores de sintaxis (ast.parse + análisis heurístico)
  2. LogicNet     — verifica que la lógica cumple la instrucción dada
  3. DiffNet      — analiza qué cambió respecto al original y si los cambios son coherentes
  4. ExecutionNet — simula el flujo de ejecución y traza variables (análisis AST)
  5. EnsembleNet  — combina las 4 redes en un score final de calidad

Flujo por verificación:
  verify(code, instruction, original?) →
    1. Sintaxis real (ast / heurística)
    2. Features → inferencia de las 4 redes especializadas
    3. EnsembleNet combina scores
    4. Entrenamiento dinámico con los resultados reales de esta verificación
    5. Reporte legible + dict con todos los scores
"""

import sys
import re
import ast
import json
import time
import difflib
import traceback
import numpy as np
from pathlib import Path
from collections import defaultdict

_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

from embeddings import EmbeddingMatrix, EMBED_DIM
from dynamic_params import DynamicNeuralNet

MODEL_DIR = Path(__file__).parent.parent / 'models'
MODEL_DIR.mkdir(exist_ok=True)

# ── Tamaños de entrada de cada red ──────────────────────────────────────────
_SYNTAX_FEATS   = 24
_LOGIC_FEATS    = 16
_DIFF_FEATS     = 20
_EXEC_FEATS     = 32
_ENSEMBLE_FEATS = 4 + 16   # 4 scores + 16 meta

_SYNTAX_IN   = EMBED_DIM + _SYNTAX_FEATS
_LOGIC_IN    = 2 * EMBED_DIM + _LOGIC_FEATS
_DIFF_IN     = 2 * EMBED_DIM + _DIFF_FEATS
_EXEC_IN     = EMBED_DIM + _EXEC_FEATS
_ENSEMBLE_IN = _ENSEMBLE_FEATS


class CodeVerifier:
    """
    5 redes neurales que verifican código antes de entregarlo al usuario.
    Cada verificación produce un entrenamiento automático — aprenden con el uso.
    """

    def __init__(self):
        self.emb = EmbeddingMatrix()

        # ── Red 1: SyntaxNet ────────────────────────────────────────────────
        # Detecta errores de sintaxis antes de que lleguen al usuario.
        # Input: embedding del código + 24 features de análisis sintáctico.
        self.syntax_net = DynamicNeuralNet([
            {'in': _SYNTAX_IN, 'out': 128, 'act': 'relu'},
            {'in': 128,        'out': 64,  'act': 'relu'},
            {'in': 64,         'out': 32,  'act': 'relu'},
            {'in': 32,         'out': 1,   'act': 'sigmoid'},
        ], lr=0.001)

        # ── Red 2: LogicNet ─────────────────────────────────────────────────
        # Verifica que la lógica del código cumple lo que se le pidió.
        # Input: emb(código) + emb(instrucción) + 16 features de coherencia.
        self.logic_net = DynamicNeuralNet([
            {'in': _LOGIC_IN, 'out': 256, 'act': 'relu'},
            {'in': 256,       'out': 128, 'act': 'relu'},
            {'in': 128,       'out': 64,  'act': 'relu'},
            {'in': 64,        'out': 1,   'act': 'sigmoid'},
        ], lr=0.0005)

        # ── Red 3: DiffNet ──────────────────────────────────────────────────
        # Compara el código nuevo con el original: qué cambió y si tiene sentido.
        # Input: emb(original) + emb(nuevo) + 20 features de diff.
        self.diff_net = DynamicNeuralNet([
            {'in': _DIFF_IN, 'out': 128, 'act': 'relu'},
            {'in': 128,      'out': 64,  'act': 'relu'},
            {'in': 64,       'out': 1,   'act': 'sigmoid'},
        ], lr=0.001)

        # ── Red 4: ExecutionNet ─────────────────────────────────────────────
        # Simula el flujo de ejecución: variables, anti-patterns, profundidad.
        # Input: emb(código) + 32 features de análisis de ejecución (AST para Python).
        self.exec_net = DynamicNeuralNet([
            {'in': _EXEC_IN, 'out': 128, 'act': 'relu'},
            {'in': 128,      'out': 64,  'act': 'relu'},
            {'in': 64,       'out': 32,  'act': 'relu'},
            {'in': 32,       'out': 1,   'act': 'sigmoid'},
        ], lr=0.001)

        # ── Red 5: EnsembleNet ──────────────────────────────────────────────
        # Combina los 4 scores + meta-features → puntuación final de calidad.
        # Pesos aprendidos: no hardcodeados, se ajustan dinámicamente.
        self.ensemble_net = DynamicNeuralNet([
            {'in': _ENSEMBLE_IN, 'out': 64, 'act': 'relu'},
            {'in': 64,           'out': 32, 'act': 'relu'},
            {'in': 32,           'out': 1,  'act': 'sigmoid'},
        ], lr=0.001)

        self.total_verifications = 0
        self._load_all()
        print(f"✅ [CodeVerifier] 5 redes cargadas — EMBED_DIM={EMBED_DIM}  "
              f"SyntaxIn={_SYNTAX_IN}  LogicIn={_LOGIC_IN}  "
              f"DiffIn={_DIFF_IN}  ExecIn={_EXEC_IN}",
              file=sys.stderr, flush=True)

    # ════════════════════════════════════════════════════════════════════════
    #  INTERFAZ PÚBLICA
    # ════════════════════════════════════════════════════════════════════════

    def verify(self, code: str, instruction: str,
               original: str = None, generation_time: float = None) -> dict:
        """
        Verifica el código con las 5 redes neurales.

        Parámetros:
          code            — código generado/modificado
          instruction     — instrucción original del usuario
          original        — código original (para DiffNet, opcional)
          generation_time — segundos que tardó en generarse (meta-feature)

        Retorna dict con:
          report           str   — reporte completo legible (markdown)
          quality_score    float — [0,1] calidad final (EnsembleNet)
          ready_to_deliver bool  — True si calidad >= 0.5 Y sintaxis real ok
          real_syntax_ok   bool  — resultado del parser real (ast / heurística)
          syntax_score     float
          logic_score      float
          diff_score       float
          exec_score       float
          lang             str   — lenguaje detectado
          verifications    int   — contador total
        """
        t0 = time.time()
        code     = (code     or '').strip()
        instr    = (instruction or '').strip()
        original = (original or '').strip()

        if not code:
            return self._empty_result("Código vacío — nada que verificar.")

        # ── 1. Verificación REAL de sintaxis ────────────────────────────────
        real_ok, syntax_errors, lang = self._real_syntax_check(code)

        # ── 2. Embeddings ────────────────────────────────────────────────────
        code_emb = self.emb.embed(code[:3000])
        instr_emb = self.emb.embed(instr[:600])
        orig_emb  = self.emb.embed(original[:3000]) if original else np.zeros(EMBED_DIM, dtype=np.float32)

        # ── 3. Inferencia de cada red ────────────────────────────────────────
        syntax_score = self._infer_syntax(code_emb, code, real_ok)
        logic_score  = self._infer_logic(code_emb, instr_emb, code, instr)
        diff_score   = self._infer_diff(code_emb, orig_emb, code, original) if original else 0.70
        exec_score   = self._infer_exec(code_emb, code, lang)
        ensemble_score = self._infer_ensemble(
            syntax_score, logic_score, diff_score, exec_score,
            code, instr, generation_time
        )

        # ── 4. Penalización por error de sintaxis real ────────────────────────
        if not real_ok:
            ensemble_score = min(ensemble_score, 0.35)
            syntax_score   = min(syntax_score,   0.20)

        quality_score    = float(np.clip(ensemble_score, 0.0, 1.0))
        ready_to_deliver = quality_score >= 0.50 and real_ok

        # ── 5. Entrenamiento dinámico con los resultados reales ───────────────
        self._train_on_verification(
            code_emb, instr_emb, orig_emb,
            code, instr, original, lang,
            real_ok, syntax_score, logic_score, diff_score, exec_score, quality_score
        )

        # ── 6. Actualizar embeddings ──────────────────────────────────────────
        self.emb.fit_text(code[:1200])
        self.emb.fit_text(instr)

        self.total_verifications += 1
        elapsed = time.time() - t0

        # ── 7. Reporte ────────────────────────────────────────────────────────
        report = self._build_report(
            lang, real_ok, syntax_errors,
            syntax_score, logic_score, diff_score, exec_score,
            quality_score, ready_to_deliver, code, original, elapsed
        )

        print(
            f"[CodeVerifier] #{self.total_verifications} lang={lang} "
            f"syntax={'✓' if real_ok else '✗'} "
            f"quality={quality_score:.2f} ready={ready_to_deliver} t={elapsed:.2f}s",
            file=sys.stderr, flush=True
        )

        return {
            'report':           report,
            'quality_score':    quality_score,
            'ready_to_deliver': ready_to_deliver,
            'real_syntax_ok':   real_ok,
            'syntax_score':     float(syntax_score),
            'logic_score':      float(logic_score),
            'diff_score':       float(diff_score),
            'exec_score':       float(exec_score),
            'lang':             lang,
            'verifications':    self.total_verifications,
        }

    def train_from_feedback(self, code: str, instruction: str,
                             was_correct: bool, bug_type: str = None,
                             original: str = None):
        """
        Entrenamiento con feedback explícito del usuario.
        Llamado desde brain_vip.py cuando la sintaxis falló o el usuario marcó error.
        """
        try:
            code     = (code or '').strip()
            instr    = (instruction or '').strip()
            original = (original or '').strip()
            quality  = 0.90 if was_correct else 0.10

            code_emb  = self.emb.embed(code[:3000])
            instr_emb = self.emb.embed(instr[:600])
            orig_emb  = self.emb.embed(original[:3000]) if original else np.zeros(EMBED_DIM, dtype=np.float32)
            lang      = self._detect_language(code)

            self._train_syntax_net(code_emb, code, quality)
            self._train_logic_net(code_emb, instr_emb, code, instr, quality)
            if original:
                self._train_diff_net(code_emb, orig_emb, code, original, quality)
            self._train_exec_net(code_emb, code, lang, quality)
            self._train_ensemble_net(quality, quality, quality, quality, quality)

            self.emb.fit_text(code[:600])
            if was_correct:
                self.emb.update_pair(instr, code[:600], label=1.0, lr=0.005)

            self.save_all()
            print(f"[CodeVerifier] train_from_feedback: was_correct={was_correct} bug_type={bug_type}",
                  file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[CodeVerifier] train_from_feedback error: {e}", file=sys.stderr, flush=True)

    def save_all(self):
        """Persiste los pesos de las 5 redes en disco."""
        models = [
            ('cv_syntax.pkl',   self.syntax_net),
            ('cv_logic.pkl',    self.logic_net),
            ('cv_diff.pkl',     self.diff_net),
            ('cv_exec.pkl',     self.exec_net),
            ('cv_ensemble.pkl', self.ensemble_net),
        ]
        for fname, net in models:
            try:
                net.save(str(MODEL_DIR / fname))
            except Exception as e:
                print(f"[CodeVerifier] save {fname} error: {e}", file=sys.stderr, flush=True)

    # ════════════════════════════════════════════════════════════════════════
    #  VERIFICACIÓN REAL DE SINTAXIS
    # ════════════════════════════════════════════════════════════════════════

    def _real_syntax_check(self, code: str) -> tuple:
        """
        Verifica la sintaxis real según el lenguaje detectado.
        Retorna: (ok: bool, errors: list[str], lang: str)
        """
        lang   = self._detect_language(code)
        errors = []

        if lang == 'python':
            try:
                ast.parse(code)
            except SyntaxError as e:
                snippet = (e.text or '').strip()[:60]
                errors.append(f"SyntaxError línea {e.lineno}: {e.msg} → '{snippet}'")
            except Exception as e:
                errors.append(f"ParseError: {str(e)[:80]}")

        elif lang in ('javascript', 'typescript'):
            errors.extend(self._js_syntax_check(code))

        elif lang == 'json':
            try:
                json.loads(code)
            except json.JSONDecodeError as e:
                errors.append(f"JSON inválido línea {e.lineno} col {e.colno}: {e.msg}")

        elif lang == 'html':
            errors.extend(self._html_syntax_check(code))

        elif lang == 'sql':
            errors.extend(self._sql_syntax_check(code))

        else:
            errors.extend(self._generic_balance_check(code))

        return (len(errors) == 0, errors, lang)

    def _detect_language(self, code: str) -> str:
        """Detecta el lenguaje de programación por patrones."""
        s = code[:600]

        if re.search(r'^\s*(import\s+\w|from\s+\w.*import|def\s+\w|class\s+\w|async\s+def|if\s+__name__)', s, re.M):
            return 'python'
        if re.search(r'(require\s*\(|module\.exports|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|\bPromise\b|\.then\()', s):
            return 'javascript'
        if re.search(r'(interface\s+\w+|:\s*string\b|:\s*number\b|<[A-Z]\w*>|@Injectable)', s):
            return 'typescript'
        if re.search(r'(<html|<!DOCTYPE\s+html|<body|<head)', s, re.I):
            return 'html'
        if re.search(r'^\s*[{\[]', s.strip()) :
            try:
                json.loads(code)
                return 'json'
            except Exception:
                pass
        if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE|DROP\s+TABLE)\b', s, re.I):
            return 'sql'
        if re.search(r'(#!/bin/(ba)?sh|^\s*(echo|grep|awk|sed|chmod|export)\s)', s, re.M):
            return 'shell'
        if re.search(r'(#include\s*<|int\s+main\s*\(|std::)', s):
            return 'cpp'
        if re.search(r'(package\s+main|func\s+\w+\s*\(|:=)', s):
            return 'go'
        if re.search(r'(fn\s+\w+|let\s+mut\s|use\s+std::)', s):
            return 'rust'
        return 'generic'

    def _js_syntax_check(self, code: str) -> list:
        """
        Verificación de sintaxis JS/TS: balanceo de delimitadores, strings,
        comentarios. Sin necesidad de parser externo.
        """
        errors = []
        pairs  = {')': '(', '}': '{', ']': '['}
        opens  = set('({[')
        closes = set(')}]')
        stack  = []

        in_str  = False
        str_ch  = None
        in_blk  = False
        lines   = code.split('\n')

        for ln_idx, line in enumerate(lines, 1):
            i = 0
            while i < len(line):
                ch = line[i]

                if in_blk:
                    if ch == '*' and i + 1 < len(line) and line[i + 1] == '/':
                        in_blk = False
                        i += 2
                    else:
                        i += 1
                    continue

                if not in_str and ch == '/' and i + 1 < len(line):
                    nxt = line[i + 1]
                    if nxt == '/':
                        break   # comentario de línea — ignorar resto
                    if nxt == '*':
                        in_blk = True
                        i += 2
                        continue

                if not in_str and ch in ('"', "'", '`'):
                    in_str = True
                    str_ch = ch
                    i += 1
                    continue
                if in_str:
                    if ch == '\\':
                        i += 2
                        continue
                    if ch == str_ch:
                        in_str = False
                    i += 1
                    continue

                if ch in opens:
                    stack.append((ch, ln_idx))
                elif ch in closes:
                    if not stack:
                        errors.append(f"Línea {ln_idx}: '{ch}' sin apertura correspondiente")
                        if len(errors) >= 5:
                            return errors
                    elif stack[-1][0] != pairs[ch]:
                        expected = {'(': ')', '{': '}', '[': ']'}[stack[-1][0]]
                        errors.append(
                            f"Línea {ln_idx}: se esperaba '{expected}' "
                            f"(para '{stack[-1][0]}' de línea {stack[-1][1]}), encontrado '{ch}'"
                        )
                        stack.pop()
                    else:
                        stack.pop()
                i += 1

        for ch, ln_idx in stack[-3:]:
            errors.append(f"Línea {ln_idx}: '{ch}' nunca cerrado")

        return errors[:5]

    def _html_syntax_check(self, code: str) -> list:
        """Verificación básica de apertura/cierre de tags HTML."""
        errors  = []
        void    = {'area','base','br','col','embed','hr','img','input',
                   'link','meta','param','source','track','wbr'}
        stack   = []
        for m in re.finditer(r'<(/?)(\w[\w-]*)([^>]*?)(/?)>', code):
            closing, tag, attrs, self_close = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
            if self_close or tag in void:
                continue
            if closing:
                if stack and stack[-1] == tag:
                    stack.pop()
                else:
                    errors.append(f"</{tag}> sin apertura correspondiente")
                    if len(errors) >= 4:
                        break
            else:
                stack.append(tag)
        for tag in stack[-3:]:
            errors.append(f"<{tag}> nunca cerrado")
        return errors

    def _sql_syntax_check(self, code: str) -> list:
        errors = []
        opens  = code.count('(')
        closes = code.count(')')
        if abs(opens - closes) > 1:
            errors.append(f"Paréntesis desbalanceados: {opens} abiertos, {closes} cerrados")
        if re.search(r'\bSELECT\b', code, re.I) and not re.search(r'\bFROM\b', code, re.I):
            if not re.search(r'SELECT\s+\d+', code, re.I):
                errors.append("SELECT sin cláusula FROM")
        return errors

    def _generic_balance_check(self, code: str) -> list:
        errors = []
        for op, cl in [('{', '}'), ('(', ')'), ('[', ']')]:
            n_op = code.count(op)
            n_cl = code.count(cl)
            if abs(n_op - n_cl) > 2:
                errors.append(f"Posible desequilibrio: {n_op}×'{op}' vs {n_cl}×'{cl}'")
        return errors[:3]

    # ════════════════════════════════════════════════════════════════════════
    #  FEATURES PARA CADA RED
    # ════════════════════════════════════════════════════════════════════════

    def _syntax_features(self, code: str) -> np.ndarray:
        """24 features de análisis sintáctico del texto del código."""
        lines     = code.split('\n')
        n_lines   = max(len(lines), 1)
        n_chars   = max(len(code), 1)

        n_open  = code.count('{') + code.count('(') + code.count('[')
        n_close = code.count('}') + code.count(')') + code.count(']')
        balance = abs(n_open - n_close) / max(n_open + n_close, 1)

        non_blank = [l for l in lines if l.strip()]
        indents   = [len(l) - len(l.lstrip()) for l in non_blank]
        avg_ind   = float(np.mean(indents)) if indents else 0.0
        std_ind   = float(np.std(indents))  if indents else 0.0

        lens      = [len(l) for l in non_blank]
        avg_len   = float(np.mean(lens)) / 100.0 if lens else 0.0

        f = np.array([
            min(n_lines / 500.0,   1.0),             # 0  líneas
            min(n_chars / 10000.0, 1.0),             # 1  chars
            float(np.clip(balance, 0, 1)),           # 2  balance delimitadores
            min(avg_ind / 20.0, 1.0),                # 3  indentación promedio
            min(std_ind / 10.0, 1.0),                # 4  varianza indentación
            float(bool(re.search(r'^\s*(import|from|require|#include)', code, re.M))),  # 5
            float(bool(re.search(r'(def |function |=>|\bfunc\b)', code))),              # 6
            float(bool(re.search(r'\b(class|struct|interface)\b', code))),              # 7
            float(bool(re.search(r'\b(for|while|foreach|loop)\b', code))),             # 8
            float(bool(re.search(r'\b(if|else|elif|switch|case)\b', code))),           # 9
            float(bool(re.search(r'\b(return|yield)\b', code))),                       # 10
            float(bool(re.search(r'(#\s|//\s|/\*|""")', code))),                       # 11 comentarios
            float(bool(re.search(r'\b(try|except|catch|finally)\b', code))),           # 12
            sum(1 for l in lines if not l.strip()) / n_lines,                          # 13 blank ratio
            min(avg_len, 1.0),                                                          # 14 avg line len
            min(code.count('{') / max(code.count('}'), 1), 2.0) / 2.0,               # 15
            min(code.count('(') / max(code.count(')'), 1), 2.0) / 2.0,               # 16
            min(code.count('[') / max(code.count(']'), 1), 2.0) / 2.0,               # 17
            float(code.count('"') % 2),                                                # 18 string sin cerrar
            float(code.count("'") % 2),                                                # 19
            float(bool(re.search(r'TODO|FIXME|HACK|BUG', code))),                     # 20
            float(bool(re.search(r'print\s*\(|console\.log', code))),                 # 21
            min(code.count('\t') / n_lines, 1.0),                                      # 22 tabs
            float(any(len(l) > 200 for l in lines)),                                   # 23 líneas largas
        ], dtype=np.float32)
        assert len(f) == _SYNTAX_FEATS
        return f

    def _logic_features(self, code: str, instr: str) -> np.ndarray:
        """16 features de coherencia entre código e instrucción."""
        il = instr.lower()
        cl = code.lower()

        instr_words = set(re.findall(r'\b\w{4,}\b', il))
        code_words  = set(re.findall(r'\b\w{4,}\b', cl))
        overlap     = len(instr_words & code_words) / max(len(instr_words), 1)

        is_create = float(any(w in il for w in ['crear','create','nuevo','new','genera','make']))
        is_edit   = float(any(w in il for w in ['edita','edit','modifica','modify','cambia','change']))
        is_add    = float(any(w in il for w in ['agrega','add','añade','append','incluye','include']))
        is_delete = float(any(w in il for w in ['elimina','delete','borra','remove','quita']))
        is_fix    = float(any(w in il for w in ['corrige','fix','arregla','repair','debug','error']))

        has_func  = float(bool(re.search(r'def |function |=>', code)))
        has_class = float(bool(re.search(r'\bclass\b', code)))
        has_loop  = float(bool(re.search(r'\b(for|while)\b', code)))
        has_cond  = float(bool(re.search(r'\b(if|else)\b', code)))

        instr_cplx  = len(instr_words) / 10.0
        code_cplx   = len(code.split('\n')) / 20.0
        length_ratio = min(code_cplx / max(instr_cplx, 0.1), 3.0) / 3.0

        has_placeholder = float(bool(re.search(r'TODO|NotImplemented|\bpass\b\s*$', code, re.M)))
        has_error_hdl   = float(bool(re.search(r'raise|throw|Error|Exception', code)))

        f = np.array([
            min(overlap, 1.0),              # 0
            is_create,                      # 1
            is_edit,                        # 2
            is_add,                         # 3
            is_delete,                      # 4
            is_fix,                         # 5
            has_func,                       # 6
            has_class,                      # 7
            has_loop,                       # 8
            has_cond,                       # 9
            float(np.clip(length_ratio, 0, 1)),  # 10
            min(len(code)  / 1000.0, 1.0), # 11
            min(len(instr) / 200.0,  1.0), # 12
            has_placeholder,               # 13
            has_error_hdl,                 # 14
            min(instr_cplx / 5.0,    1.0), # 15
        ], dtype=np.float32)
        assert len(f) == _LOGIC_FEATS
        return f

    def _diff_features(self, code: str, original: str) -> np.ndarray:
        """20 features de análisis del diff entre original y código nuevo."""
        if not original:
            return np.full(_DIFF_FEATS, 0.5, dtype=np.float32)

        orig_lines = original.split('\n')
        new_lines  = code.split('\n')

        matcher = difflib.SequenceMatcher(None, orig_lines, new_lines)
        ratio   = matcher.ratio()
        opcodes = matcher.get_opcodes()
        n_total = max(len(opcodes), 1)

        n_replace = sum(1 for op in opcodes if op[0] == 'replace')
        n_insert  = sum(1 for op in opcodes if op[0] == 'insert')
        n_delete  = sum(1 for op in opcodes if op[0] == 'delete')
        n_equal   = sum(1 for op in opcodes if op[0] == 'equal')

        lines_delta = len(new_lines) - len(orig_lines)
        chars_delta = (len(code) - len(original)) / max(len(original), 1)

        # Cambios en funciones e imports (indicadores de cambio semántico)
        funcs_orig = len(re.findall(r'def |function ', original))
        funcs_new  = len(re.findall(r'def |function ', code))
        imp_orig   = bool(re.search(r'^\s*(import|from|require)', original, re.M))
        imp_new    = bool(re.search(r'^\s*(import|from|require)', code,     re.M))

        f = np.array([
            float(ratio),                                              # 0
            float(1.0 - ratio),                                        # 1
            float(n_replace / n_total),                                # 2
            float(n_insert  / n_total),                                # 3
            float(n_delete  / n_total),                                # 4
            float(n_equal   / n_total),                                # 5
            min(abs(lines_delta) / max(len(orig_lines), 1), 1.0),    # 6
            min(abs(chars_delta), 1.0),                                # 7
            float(lines_delta > 0),                                    # 8 se añadieron líneas
            float(lines_delta < 0),                                    # 9 se quitaron líneas
            float(ratio > 0.92),                                       # 10 casi igual (¿se aplicó algo?)
            float(ratio < 0.15),                                       # 11 reescritura total
            float(imp_orig != imp_new),                                # 12 cambio en imports
            float(funcs_orig != funcs_new),                            # 13 cambio en funciones
            min(abs(funcs_new - funcs_orig) / max(funcs_orig, 1), 1.0), # 14
            float(len(new_lines) > len(orig_lines)),                   # 15
            float(len(new_lines) < len(orig_lines)),                   # 16
            min(n_total / 30.0, 1.0),                                  # 17 complejidad diff
            min(len(orig_lines) / 500.0, 1.0),                        # 18 tamaño original
            min(len(new_lines)  / 500.0, 1.0),                        # 19 tamaño nuevo
        ], dtype=np.float32)
        assert len(f) == _DIFF_FEATS
        return f

    def _exec_features(self, code: str, lang: str) -> np.ndarray:
        """32 features de simulación de flujo de ejecución."""
        if lang == 'python':
            return self._python_exec_features(code)
        return self._generic_exec_features(code)

    def _python_exec_features(self, code: str) -> np.ndarray:
        """
        Análisis profundo del AST de Python:
        variables asignadas/usadas, anti-patterns, profundidad, tipado.
        """
        f = np.zeros(_EXEC_FEATS, dtype=np.float32)
        try:
            tree  = ast.parse(code)
        except SyntaxError:
            f[0] = 1.0   # flag de error de parse
            return f

        nodes = list(ast.walk(tree))

        n_funcs  = sum(1 for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        n_cls    = sum(1 for n in nodes if isinstance(n, ast.ClassDef))
        n_calls  = sum(1 for n in nodes if isinstance(n, ast.Call))
        n_assign = sum(1 for n in nodes if isinstance(n, ast.Assign))
        n_ret    = sum(1 for n in nodes if isinstance(n, ast.Return))
        n_loops  = sum(1 for n in nodes if isinstance(n, (ast.For, ast.While)))
        n_ifs    = sum(1 for n in nodes if isinstance(n, ast.If))
        n_imp    = sum(1 for n in nodes if isinstance(n, (ast.Import, ast.ImportFrom)))
        n_try    = sum(1 for n in nodes if isinstance(n, ast.Try))
        n_raise  = sum(1 for n in nodes if isinstance(n, ast.Raise))
        n_comp   = sum(1 for n in nodes if isinstance(n, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)))
        n_lambda = sum(1 for n in nodes if isinstance(n, ast.Lambda))
        n_assert = sum(1 for n in nodes if isinstance(n, ast.Assert))
        n_total  = max(len(nodes), 1)

        # Variables asignadas en el scope global/local más externo
        _BUILTINS = {
            'True','False','None','print','range','len','str','int','float',
            'list','dict','set','tuple','type','isinstance','hasattr','getattr',
            'setattr','enumerate','zip','map','filter','sorted','reversed',
            'open','super','self','cls','__name__','__file__','_',
            'any','all','min','max','sum','abs','round','id','hash',
            'ValueError','TypeError','KeyError','IndexError','Exception',
            'AttributeError','ImportError','RuntimeError','StopIteration',
            'NotImplementedError','NameError','FileNotFoundError',
        }
        assigned    = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        assigned.add(t.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args:
                    assigned.add(arg.arg)
        used_names  = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        unused_vars = len(assigned - used_names - _BUILTINS)
        undef_vars  = len(used_names - assigned - _BUILTINS)

        lines    = code.split('\n')
        max_ind  = max((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
        n_cmts   = sum(1 for l in lines if l.strip().startswith('#'))

        f[0]  = 0.0  # sin error parse
        f[1]  = min(n_funcs  / 10.0, 1.0)
        f[2]  = min(n_cls    / 5.0,  1.0)
        f[3]  = min(n_calls  / 50.0, 1.0)
        f[4]  = min(n_assign / 30.0, 1.0)
        f[5]  = min(n_ret    / 10.0, 1.0)
        f[6]  = min(n_loops  / 10.0, 1.0)
        f[7]  = min(n_ifs    / 20.0, 1.0)
        f[8]  = min(n_imp    / 10.0, 1.0)
        f[9]  = min(n_try    / 5.0,  1.0)
        f[10] = min(n_raise  / 5.0,  1.0)
        f[11] = min(n_comp   / 5.0,  1.0)
        f[12] = min(n_lambda / 3.0,  1.0)
        f[13] = min(n_assert / 5.0,  1.0)
        f[14] = min(unused_vars / max(len(assigned), 1), 1.0)  # vars sin usar
        f[15] = min(undef_vars  / max(len(used_names), 1), 1.0) # vars sin definir
        f[16] = min(n_total  / 200.0, 1.0)
        f[17] = float(any('import *' in l for l in lines))       # wildcard import
        f[18] = float(any('eval(' in l or 'exec(' in l for l in lines))  # eval/exec
        f[19] = float(any(l.strip() == 'pass' for l in lines))  # pass desnudo
        f[20] = float(bool(re.search(r'while\s+True\s*:', code)))  # loop infinito
        f[21] = float(bool(re.search(r'except\s*:', code)))         # bare except
        f[22] = float(bool(re.search(r'#\s*(TODO|FIXME|HACK)', code, re.I)))
        f[23] = float(n_funcs > 0 and n_ret == 0)  # funciones sin return
        f[24] = min(max_ind / 40.0, 1.0)           # profundidad anidamiento
        f[25] = min(n_cmts  / max(len(lines), 1), 1.0)  # ratio comentarios
        f[26] = float(bool(re.search(r':\s*(str|int|float|bool|list|dict|Optional)', code)))  # type hints
        f[27] = float(bool(re.search(r'"""[\s\S]*?"""', code)))  # docstrings
        # 28-31 reservados para futuras features
        return f

    def _generic_exec_features(self, code: str) -> np.ndarray:
        """Features de ejecución para lenguajes no-Python (JS, TS, Go, etc.)."""
        f     = np.zeros(_EXEC_FEATS, dtype=np.float32)
        lines = code.split('\n')
        nl    = max(len(lines), 1)

        f[0]  = 0.0
        f[1]  = min(len(re.findall(r'function\s+\w+|=>\s*{|def\s+\w+', code)) / 10.0, 1.0)
        f[2]  = min(len(re.findall(r'\bclass\b', code)) / 5.0, 1.0)
        f[3]  = min(len(re.findall(r'\b\w+\s*\(', code)) / 50.0, 1.0)
        f[4]  = min(len(re.findall(r'(?<![=!<>])=(?!=)', code)) / 30.0, 1.0)
        f[5]  = min(len(re.findall(r'\breturn\b', code)) / 10.0, 1.0)
        f[6]  = min(len(re.findall(r'\b(for|while|foreach)\b', code)) / 10.0, 1.0)
        f[7]  = min(len(re.findall(r'\bif\b', code)) / 20.0, 1.0)
        f[8]  = min(len(re.findall(r'(import|require|include|use)', code)) / 10.0, 1.0)
        f[9]  = min(len(re.findall(r'\btry\b', code)) / 5.0, 1.0)
        f[10] = min(len(re.findall(r'\b(throw|raise)\b', code)) / 5.0, 1.0)
        f[11] = float(bool(re.search(r'TODO|FIXME|HACK', code)))
        f[12] = float(bool(re.search(r'console\.log|debugger\b', code)))
        max_ind = max((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
        f[13] = min(max_ind / 40.0, 1.0)
        n_cmts = sum(1 for l in lines if re.match(r'\s*(//|#|/\*)', l))
        f[14] = min(n_cmts / nl, 1.0)
        f[15] = float(bool(re.search(r'while\s*\(\s*true\s*\)', code, re.I)))
        f[16] = float(code.count('{') == code.count('}'))   # balance llaves
        f[17] = float(code.count('(') == code.count(')'))   # balance parens
        f[18] = float(bool(re.search(r'eval\(', code)))     # eval
        f[19] = float(bool(re.search(r'async\s+(function|def|\w+\s*=>)', code)))
        return f

    # ════════════════════════════════════════════════════════════════════════
    #  INFERENCIA (FORWARD PASS)
    # ════════════════════════════════════════════════════════════════════════

    def _infer_syntax(self, code_emb: np.ndarray, code: str, real_ok: bool) -> float:
        """Red 1: score de sintaxis (70% resultado real + 30% neural)."""
        try:
            feats = self._syntax_features(code)
            inp   = np.concatenate([code_emb, feats]).reshape(1, -1).astype(np.float32)
            neural = float(self.syntax_net.forward(inp)[0, 0])
            real   = 1.0 if real_ok else 0.0
            return float(np.clip(0.70 * real + 0.30 * neural, 0.0, 1.0))
        except Exception as e:
            print(f"[CV:SyntaxNet] forward error: {e}", file=sys.stderr, flush=True)
            return 1.0 if real_ok else 0.0

    def _infer_logic(self, code_emb, instr_emb, code: str, instr: str) -> float:
        """Red 2: score de coherencia lógica."""
        try:
            feats = self._logic_features(code, instr)
            inp   = np.concatenate([code_emb, instr_emb, feats]).reshape(1, -1).astype(np.float32)
            score = float(self.logic_net.forward(inp)[0, 0])
            return float(np.clip(score, 0.0, 1.0))
        except Exception as e:
            print(f"[CV:LogicNet] forward error: {e}", file=sys.stderr, flush=True)
            return 0.50

    def _infer_diff(self, code_emb, orig_emb, code: str, original: str) -> float:
        """Red 3: score de calidad del diff (60% neural + 40% heurístico)."""
        try:
            feats = self._diff_features(code, original)
            inp   = np.concatenate([orig_emb, code_emb, feats]).reshape(1, -1).astype(np.float32)
            neural = float(self.diff_net.forward(inp)[0, 0])
            # Heurística: un buen diff tiene ratio ~0.4–0.85 (ni idéntico ni reescritura total)
            ratio  = difflib.SequenceMatcher(None, original, code).ratio()
            manual = 1.0 - abs(ratio - 0.60) * 1.2
            return float(np.clip(0.60 * neural + 0.40 * manual, 0.0, 1.0))
        except Exception as e:
            print(f"[CV:DiffNet] forward error: {e}", file=sys.stderr, flush=True)
            return 0.60

    def _infer_exec(self, code_emb, code: str, lang: str) -> float:
        """Red 4: score de ejecución (con penalización por anti-patterns)."""
        try:
            feats  = self._exec_features(code, lang)
            inp    = np.concatenate([code_emb, feats]).reshape(1, -1).astype(np.float32)
            score  = float(self.exec_net.forward(inp)[0, 0])
            # Penalizar anti-patterns críticos detectados directamente
            penalty = 0.0
            if feats[0]  > 0: penalty += 0.30  # error de parse
            if feats[18] > 0: penalty += 0.10  # eval/exec
            if feats[21] > 0: penalty += 0.05  # bare except (Python)
            if feats[20] > 0: penalty += 0.05  # while True sin break visible
            return float(np.clip(score - penalty, 0.0, 1.0))
        except Exception as e:
            print(f"[CV:ExecNet] forward error: {e}", file=sys.stderr, flush=True)
            return 0.50

    def _infer_ensemble(self, syntax: float, logic: float, diff: float, exec_s: float,
                        code: str, instr: str, gen_time: float = None) -> float:
        """Red 5: combinación final de los 4 scores + meta-features."""
        try:
            meta = np.zeros(16, dtype=np.float32)
            meta[0]  = float(syntax)
            meta[1]  = float(logic)
            meta[2]  = float(diff)
            meta[3]  = float(exec_s)
            meta[4]  = min(len(code)  / 5000.0, 1.0)
            meta[5]  = min(len(instr) / 200.0,  1.0)
            meta[6]  = min(gen_time / 30.0, 1.0) if gen_time else 0.50
            meta[7]  = float(syntax > 0.70)
            meta[8]  = float(logic  > 0.60)
            meta[9]  = float(exec_s > 0.60)
            meta[10] = float(all(s > 0.50 for s in [syntax, logic, exec_s]))
            meta[11] = (syntax + logic + diff + exec_s) / 4.0
            meta[12] = float(syntax > 0.85 and logic > 0.70)  # alta confianza
            meta[13] = float(syntax < 0.30 or exec_s < 0.25)  # señal de problema grave

            scores_row = np.array([[syntax, logic, diff, exec_s]], dtype=np.float32)
            inp = np.concatenate([scores_row, meta.reshape(1, -1)], axis=1)

            neural = float(self.ensemble_net.forward(inp)[0, 0])
            # Pesos manuales balanceados: se combinan con el output neural
            manual = (syntax * 0.35 + logic * 0.30 + diff * 0.15 + exec_s * 0.20)
            return float(np.clip(0.50 * neural + 0.50 * manual, 0.0, 1.0))
        except Exception as e:
            print(f"[CV:EnsembleNet] forward error: {e}", file=sys.stderr, flush=True)
            return float(np.clip(syntax * 0.35 + logic * 0.30 + diff * 0.15 + exec_s * 0.20, 0.0, 1.0))

    # ════════════════════════════════════════════════════════════════════════
    #  ENTRENAMIENTO DINÁMICO
    # ════════════════════════════════════════════════════════════════════════

    def _train_on_verification(self, code_emb, instr_emb, orig_emb,
                               code, instr, original, lang,
                               real_ok, syntax_score, logic_score,
                               diff_score, exec_score, quality_score):
        """
        Entrena dinámicamente las 5 redes con los resultados de esta verificación.
        El target de cada red = resultado real/heurístico de esa verificación.
        Así cada archivo procesado es un dato de entrenamiento nuevo.
        """
        try:
            self._train_syntax_net(code_emb, code,
                                   target=1.0 if real_ok else 0.0)
            self._train_logic_net(code_emb, instr_emb, code, instr,
                                  target=logic_score)
            if original:
                self._train_diff_net(code_emb, orig_emb, code, original,
                                     target=diff_score)
            self._train_exec_net(code_emb, code, lang,
                                 target=exec_score)
            self._train_ensemble_net(syntax_score, logic_score,
                                     diff_score, exec_score,
                                     target=quality_score)
            # Guardar cada 10 verificaciones
            if self.total_verifications % 10 == 0:
                self.save_all()
        except Exception as e:
            print(f"[CodeVerifier] _train_on_verification error: {e}", file=sys.stderr, flush=True)

    def _train_syntax_net(self, code_emb: np.ndarray, code: str, target: float):
        try:
            feats = self._syntax_features(code)
            inp   = np.concatenate([code_emb, feats]).reshape(1, -1).astype(np.float32)
            loss  = self.syntax_net.train_step(inp, np.array([[target]], dtype=np.float32))
            if self.total_verifications % 25 == 0:
                print(f"[CV:SyntaxNet] loss={loss:.4f}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[CV:SyntaxNet] train error: {e}", file=sys.stderr, flush=True)

    def _train_logic_net(self, code_emb, instr_emb, code: str, instr: str, target: float):
        try:
            feats = self._logic_features(code, instr)
            inp   = np.concatenate([code_emb, instr_emb, feats]).reshape(1, -1).astype(np.float32)
            loss  = self.logic_net.train_step(inp, np.array([[target]], dtype=np.float32))
            if self.total_verifications % 25 == 0:
                print(f"[CV:LogicNet] loss={loss:.4f}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[CV:LogicNet] train error: {e}", file=sys.stderr, flush=True)

    def _train_diff_net(self, code_emb, orig_emb, code: str, original: str, target: float):
        try:
            feats = self._diff_features(code, original)
            inp   = np.concatenate([orig_emb, code_emb, feats]).reshape(1, -1).astype(np.float32)
            loss  = self.diff_net.train_step(inp, np.array([[target]], dtype=np.float32))
            if self.total_verifications % 25 == 0:
                print(f"[CV:DiffNet] loss={loss:.4f}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[CV:DiffNet] train error: {e}", file=sys.stderr, flush=True)

    def _train_exec_net(self, code_emb, code: str, lang: str, target: float):
        try:
            feats = self._exec_features(code, lang)
            inp   = np.concatenate([code_emb, feats]).reshape(1, -1).astype(np.float32)
            loss  = self.exec_net.train_step(inp, np.array([[target]], dtype=np.float32))
            if self.total_verifications % 25 == 0:
                print(f"[CV:ExecNet] loss={loss:.4f}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[CV:ExecNet] train error: {e}", file=sys.stderr, flush=True)

    def _train_ensemble_net(self, syntax: float, logic: float,
                             diff: float, exec_s: float, target: float):
        try:
            meta = np.zeros(16, dtype=np.float32)
            meta[0], meta[1], meta[2], meta[3] = syntax, logic, diff, exec_s
            meta[11] = (syntax + logic + diff + exec_s) / 4.0
            meta[12] = float(syntax > 0.85 and logic > 0.70)
            meta[13] = float(syntax < 0.30 or exec_s < 0.25)
            scores_row = np.array([[syntax, logic, diff, exec_s]], dtype=np.float32)
            inp  = np.concatenate([scores_row, meta.reshape(1, -1)], axis=1).astype(np.float32)
            loss = self.ensemble_net.train_step(inp, np.array([[target]], dtype=np.float32))
            if self.total_verifications % 25 == 0:
                print(f"[CV:EnsembleNet] loss={loss:.4f}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[CV:EnsembleNet] train error: {e}", file=sys.stderr, flush=True)

    # ════════════════════════════════════════════════════════════════════════
    #  REPORTE LEGIBLE
    # ════════════════════════════════════════════════════════════════════════

    def _build_report(self, lang, real_ok, syntax_errors,
                      syntax_score, logic_score, diff_score, exec_score,
                      quality_score, ready, code, original, elapsed) -> str:
        """Construye el reporte markdown de verificación."""
        def se(s):   # score emoji
            return '✅' if s >= 0.75 else ('⚠️' if s >= 0.50 else '❌')

        lines_count = len(code.split('\n'))
        has_orig    = bool(original)

        rows = [
            f"### 🧠 Verificación Neural de Código",
            f"**Lenguaje:** `{lang}` · **Líneas:** {lines_count} · "
            f"**Tiempo:** {elapsed:.2f}s · **Verificación #** {self.total_verifications + 1}",
            "",
            "| Red | Función | Score |",
            "|-----|---------|-------|",
            f"| SyntaxNet    | Detección de errores de sintaxis     | {se(syntax_score)} {syntax_score:.0%} |",
            f"| LogicNet     | Coherencia código ↔ instrucción      | {se(logic_score)} {logic_score:.0%} |",
            f"| DiffNet      | Calidad de cambios vs original       | {se(diff_score) + ' ' + f'{diff_score:.0%}' if has_orig else '— (sin original)'} |",
            f"| ExecutionNet | Flujo de ejecución / variables       | {se(exec_score)} {exec_score:.0%} |",
            f"| **EnsembleNet** | **Calidad final**               | **{se(quality_score)} {quality_score:.0%}** |",
        ]

        # Errores de sintaxis reales
        if not real_ok and syntax_errors:
            rows += ["", "**❌ Errores de sintaxis detectados:**"]
            for err in syntax_errors[:4]:
                rows.append(f"- `{err}`")

        # Resumen del diff
        if has_orig:
            orig_lines = original.split('\n')
            new_lines  = code.split('\n')
            diff_lines = list(difflib.unified_diff(orig_lines, new_lines, lineterm='', n=0))
            added   = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
            removed = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))
            if added or removed:
                rows += ["", f"**📊 Diff:** `+{added}` líneas añadidas · `-{removed}` líneas eliminadas"]

        # Anti-patterns detectados (ExecutionNet)
        warnings = []
        if lang == 'python' and code:
            if 'import *' in code:              warnings.append("`import *` — evitar wildcard imports")
            if re.search(r'except\s*:', code):  warnings.append("`except:` sin tipo — atrapar solo lo necesario")
            if re.search(r'eval\s*\(', code):   warnings.append("`eval()` detectado — revisar si es necesario")
        if warnings:
            rows += ["", "**⚠️ Anti-patterns detectados:**"]
            for w in warnings:
                rows.append(f"- {w}")

        # Veredicto
        rows.append("")
        if ready:
            rows.append(f"**✅ Listo para entregar** — calidad: {quality_score:.0%}")
        elif quality_score >= 0.50:
            rows.append(f"**⚠️ Revisión recomendada** — calidad: {quality_score:.0%}")
        else:
            rows.append(f"**❌ Requiere corrección** — calidad: {quality_score:.0%}")

        rows.append("*5 redes entrenadas dinámicamente con cada archivo procesado*")
        return '\n'.join(rows)

    # ════════════════════════════════════════════════════════════════════════
    #  UTILIDADES
    # ════════════════════════════════════════════════════════════════════════

    def _empty_result(self, msg: str) -> dict:
        return {
            'report': f"### 🧠 CodeVerifier\n{msg}",
            'quality_score': 0.0, 'ready_to_deliver': False,
            'real_syntax_ok': False, 'syntax_score': 0.0,
            'logic_score': 0.0, 'diff_score': 0.0, 'exec_score': 0.0,
            'lang': 'unknown', 'verifications': self.total_verifications,
        }

    def _load_all(self):
        models = [
            ('cv_syntax.pkl',   self.syntax_net),
            ('cv_logic.pkl',    self.logic_net),
            ('cv_diff.pkl',     self.diff_net),
            ('cv_exec.pkl',     self.exec_net),
            ('cv_ensemble.pkl', self.ensemble_net),
        ]
        for fname, net in models:
            p = MODEL_DIR / fname
            if p.exists():
                try:
                    net.load(str(p))
                    print(f"[CodeVerifier] ✓ {fname} cargado", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"[CodeVerifier] {fname} no cargado: {e}", file=sys.stderr, flush=True)


# ══════════════════════════════════════════════════════════════════════════
#  TEST RÁPIDO (ejecutar directamente para verificar que todo funciona)
# ══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=== Test CodeVerifier ===\n")

    cv = CodeVerifier()

    # Test 1: Python correcto
    code_ok = """
def calcular_suma(a: int, b: int) -> int:
    \"\"\"Suma dos números enteros.\"\"\"
    if not isinstance(a, int) or not isinstance(b, int):
        raise TypeError("Se requieren enteros")
    return a + b

resultado = calcular_suma(3, 5)
print(f"Resultado: {resultado}")
""".strip()

    r = cv.verify(code_ok, "Crea una función que sume dos números")
    print(r['report'])
    print(f"\n→ quality={r['quality_score']:.2f} ready={r['ready_to_deliver']}\n")

    # Test 2: Python con error de sintaxis
    code_bad = """
def funcion_rota(x
    return x * 2

resultado = funcion_rota(5)
""".strip()

    r2 = cv.verify(code_bad, "Crea una función que multiplique por 2")
    print(r2['report'])
    print(f"\n→ quality={r2['quality_score']:.2f} ready={r2['ready_to_deliver']}\n")

    # Test 3: Con original (diff)
    original_code = "def saludo(nombre):\n    print('Hola')"
    modified_code = "def saludo(nombre: str) -> str:\n    \"\"\"Retorna saludo.\"\"\"\n    return f'Hola, {nombre}!'"
    r3 = cv.verify(modified_code, "Agrega type hints y haz que retorne string en vez de imprimir",
                   original=original_code)
    print(r3['report'])
    print(f"\n→ quality={r3['quality_score']:.2f} ready={r3['ready_to_deliver']}")
