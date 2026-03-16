#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXUS - Sistema de Embeddings v3.1 (FIXED)
Convierte texto en vectores densos usando n-gramas de caracteres + TF-IDF.
No requiere modelos externos; aprende la distribución de tus propios textos.
"""

import numpy as np
import re
import pickle
import os
from collections import defaultdict, Counter
from pathlib import Path
from typing import List, Dict


EMBED_DIM = 128  # Dimensión del vector final
NGRAM_RANGE = (2, 5)  # n-gramas de caracteres (2..5 chars)
MAX_VOCAB = 16384  # Vocabulario máximo de n-gramas


def _ngrams(text: str, n: int) -> List[str]:
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()
    padded = f"#{text}#"
    return [padded[i:i+n] for i in range(len(padded) - n + 1)]


def _all_ngrams(text: str) -> List[str]:
    result = []
    for n in range(NGRAM_RANGE[0], NGRAM_RANGE[1] + 1):
        result.extend(_ngrams(text, n))
    return result


class EmbeddingMatrix:
    """
    Aprende una matriz de embeddings E ∈ R^{vocab × EMBED_DIM}.
    Cada n-grama se mapea a una fila. El embedding de un texto
    es la media de los embeddings de sus n-gramas, normalizada.
    """

    def __init__(self, model_path: str = 'models/embeddings.pkl'):
        self.model_path = model_path
        self.vocab: Dict[str, int] = {}          # ngram → índice
        self.E: np.ndarray = np.empty((0, EMBED_DIM))  # matriz de embeddings
        self.idf: Dict[str, float] = {}          # IDF ponderado
        self.doc_count = 0
        self.ngram_doc_freq: Dict[str, int] = defaultdict(int)
        self._load()

    # ── Actualización incremental del vocabulario ──
    def fit_text(self, text: str):
        """Registra un texto nuevo; actualiza IDF."""
        # ✅ FIX #12: Validar texto vacío
        if not text or not text.strip():
            return
        
        grams = set(_all_ngrams(text))
        self.doc_count += 1

        new_grams = []
        for g in grams:
            self.ngram_doc_freq[g] += 1
            if g not in self.vocab:
                if len(self.vocab) < MAX_VOCAB:
                    idx = len(self.vocab)
                    self.vocab[g] = idx
                    new_grams.append(idx)

        # Ampliar matriz si hay nuevos n-gramas
        if new_grams:
            extra = np.random.randn(len(new_grams), EMBED_DIM) * 0.1
            if self.E.shape[0] == 0:
                self.E = extra
            else:
                self.E = np.vstack([self.E, extra])

        # Actualizar IDF con suavizado Laplace
        for g, df in self.ngram_doc_freq.items():
            self.idf[g] = np.log((self.doc_count + 1) / (df + 1)) + 1.0

    # ── Embedding de un texto ──
    def embed(self, text: str) -> np.ndarray:
        """
        ✅ FIX #12: Devuelve vector normalizado con validación de entrada
        """
        # ✅ Validar texto vacío
        if not text or not text.strip():
            return np.zeros(EMBED_DIM, dtype=np.float32)
        
        grams = _all_ngrams(text)
        if not grams:
            return np.zeros(EMBED_DIM, dtype=np.float32)

        freq = Counter(grams)
        vecs = []
        weights = []

        for gram, count in freq.items():
            if gram in self.vocab:
                idx = self.vocab[gram]
                if idx < len(self.E):
                    tf = 1 + np.log(count)
                    idf = self.idf.get(gram, 1.0)
                    vecs.append(self.E[idx])
                    weights.append(tf * idf)

        if not vecs:
            # Fallback: hash determinístico pero diferente para cada texto
            hash_val = hash(text) % (2**31)
            rng = np.random.RandomState(hash_val)
            vec = rng.randn(EMBED_DIM).astype(np.float32)
            # Normalizar
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            return vec

        weights = np.array(weights)
        weights /= (weights.sum() + 1e-8)
        vec = np.average(vecs, axis=0, weights=weights).astype(np.float32)

        # L2 normalization
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        
        return vec

    # ── Ajuste fino por feedback ──
    def update_pair(self, text_a: str, text_b: str, label: float, lr: float = 0.005):
        """
        Contrastive update:
        label=1 → acercar vectores (positivo/relevante)
        label=0 → alejar vectores (negativo/no relevante)
        """
        # ✅ Validar inputs
        if not text_a or not text_b:
            return
        
        va = self.embed(text_a)
        vb = self.embed(text_b)
        cos = float(np.dot(va, vb))  # ya están normalizados

        error = label - cos  # error respecto a objetivo

        grams_a = list(set(_all_ngrams(text_a)) & set(self.vocab.keys()))
        grams_b = list(set(_all_ngrams(text_b)) & set(self.vocab.keys()))

        # Gradient paso (simplificado)
        for g in grams_a:
            idx = self.vocab[g]
            if idx < len(self.E):
                self.E[idx] += lr * error * vb

        for g in grams_b:
            idx = self.vocab[g]
            if idx < len(self.E):
                self.E[idx] += lr * error * va

    def similarity(self, text_a: str, text_b: str) -> float:
        """Calcula similitud coseno entre dos textos"""
        # ✅ Validar inputs
        if not text_a or not text_b:
            return 0.0
        
        va = self.embed(text_a)
        vb = self.embed(text_b)
        return float(np.dot(va, vb))
    
    def vocab_size(self) -> int:
        """Retorna el tamaño del vocabulario"""
        return len(self.vocab)

    # ── Persistencia ──
    def _load(self):
        if not os.path.exists(self.model_path):
            return
        try:
            with open(self.model_path, 'rb') as f:
                state = pickle.load(f)
            self.vocab = state['vocab']
            self.E = state['E']
            self.idf = state['idf']
            self.doc_count = state['doc_count']
            self.ngram_doc_freq = defaultdict(int, state['ngram_doc_freq'])
            print(f"[Embeddings] Cargados {len(self.vocab)} n-gramas", flush=True)
        except Exception as e:
            print(f"[Embeddings] Error cargando: {e}", flush=True)

    def save(self):
        Path(self.model_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            state = {
                'vocab': self.vocab,
                'E': self.E,
                'idf': self.idf,
                'doc_count': self.doc_count,
                'ngram_doc_freq': dict(self.ngram_doc_freq)
            }
            with open(self.model_path, 'wb') as f:
                pickle.dump(state, f)
        except Exception as e:
            print(f"[Embeddings] Error guardando: {e}", flush=True)

    def stats(self) -> dict:
        return {
            'vocab_size': len(self.vocab),
            'embed_dim': EMBED_DIM,
            'docs_seen': self.doc_count,
            'matrix_shape': list(self.E.shape)
        }
