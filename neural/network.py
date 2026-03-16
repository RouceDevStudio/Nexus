#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXUS - Red Neuronal Real con Backpropagation y Aprendizaje Online
Una red genuina que aprende de cada interacción.
"""

import numpy as np
import pickle
import os
import math
from pathlib import Path


# ─────────────────────────────────────────────
#  CAPA NEURONAL CON BACKPROP REAL
# ─────────────────────────────────────────────

class DenseLayer:
    """Capa densa con inicialización He, dropout opcional y backprop."""

    def __init__(self, in_size: int, out_size: int, activation: str = 'relu', dropout_rate: float = 0.0):
        # He initialization (mejor para ReLU)
        self.W = np.random.randn(in_size, out_size) * np.sqrt(2.0 / in_size)
        self.b = np.zeros((1, out_size))
        self.activation = activation
        self.dropout_rate = dropout_rate

        # Estado para backprop
        self._x = None
        self._z = None
        self._mask = None

        # Momentos Adam
        self.mW = np.zeros_like(self.W)
        self.vW = np.zeros_like(self.W)
        self.mb = np.zeros_like(self.b)
        self.vb = np.zeros_like(self.b)
        self.t = 0

    # ── Activaciones ──────────────────────────
    def _act(self, z):
        if self.activation == 'relu':
            return np.maximum(0, z)
        elif self.activation == 'leaky_relu':
            return np.where(z > 0, z, 0.01 * z)
        elif self.activation == 'sigmoid':
            return 1 / (1 + np.exp(-np.clip(z, -500, 500)))
        elif self.activation == 'tanh':
            return np.tanh(z)
        elif self.activation == 'linear':
            return z
        return np.maximum(0, z)  # default relu

    def _act_grad(self, z):
        if self.activation == 'relu':
            return (z > 0).astype(float)
        elif self.activation == 'leaky_relu':
            return np.where(z > 0, 1.0, 0.01)
        elif self.activation == 'sigmoid':
            s = 1 / (1 + np.exp(-np.clip(z, -500, 500)))
            return s * (1 - s)
        elif self.activation == 'tanh':
            return 1 - np.tanh(z) ** 2
        elif self.activation == 'linear':
            return np.ones_like(z)
        return (z > 0).astype(float)

    # ── Forward ───────────────────────────────
    def forward(self, x: np.ndarray, training: bool = False) -> np.ndarray:
        self._x = x
        self._z = x @ self.W + self.b
        out = self._act(self._z)

        # Dropout durante entrenamiento
        if training and self.dropout_rate > 0:
            self._mask = (np.random.rand(*out.shape) > self.dropout_rate) / (1 - self.dropout_rate)
            out = out * self._mask
        else:
            self._mask = None

        return out

    # ── Backward (Adam optimizer) ──────────────
    def backward(self, grad_out: np.ndarray, lr: float = 1e-3,
                 beta1: float = 0.9, beta2: float = 0.999, eps: float = 1e-8):
        if self._mask is not None:
            grad_out = grad_out * self._mask

        dz = grad_out * self._act_grad(self._z)
        dW = self._x.T @ dz
        db = np.sum(dz, axis=0, keepdims=True)
        dx = dz @ self.W.T

        # Adam update
        self.t += 1
        self.mW = beta1 * self.mW + (1 - beta1) * dW
        self.vW = beta2 * self.vW + (1 - beta2) * dW ** 2
        mW_c = self.mW / (1 - beta1 ** self.t)
        vW_c = self.vW / (1 - beta2 ** self.t)
        self.W -= lr * mW_c / (np.sqrt(vW_c) + eps)

        self.mb = beta1 * self.mb + (1 - beta1) * db
        self.vb = beta2 * self.vb + (1 - beta2) * db ** 2
        mb_c = self.mb / (1 - beta1 ** self.t)
        vb_c = self.vb / (1 - beta2 ** self.t)
        self.b -= lr * mb_c / (np.sqrt(vb_c) + eps)

        return dx

    def get_state(self):
        return {'W': self.W, 'b': self.b, 'mW': self.mW, 'vW': self.vW,
                'mb': self.mb, 'vb': self.vb, 't': self.t,
                'activation': self.activation, 'dropout_rate': self.dropout_rate}

    def set_state(self, state):
        self.W = state['W']
        self.b = state['b']
        self.mW = state.get('mW', np.zeros_like(self.W))
        self.vW = state.get('vW', np.zeros_like(self.W))
        self.mb = state.get('mb', np.zeros_like(self.b))
        self.vb = state.get('vb', np.zeros_like(self.b))
        self.t  = state.get('t', 0)


# ─────────────────────────────────────────────
#  RED COMPLETA
# ─────────────────────────────────────────────

class NeuralNet:
    """
    Red neuronal profunda.
    Arquitectura: [input] → [hidden...] → [output]
    Entrenamiento online (1 ejemplo a la vez) o por batches.
    """

    def __init__(self, layers_cfg: list, lr: float = 1e-3):
        """
        layers_cfg: lista de dicts, ej:
            [{'in':64,'out':128,'act':'relu','drop':0.1}, ...]
        """
        self.layers: list[DenseLayer] = []
        self.lr = lr
        self.loss_history: list[float] = []

        for cfg in layers_cfg:
            self.layers.append(DenseLayer(
                cfg['in'], cfg['out'],
                activation=cfg.get('act', 'relu'),
                dropout_rate=cfg.get('drop', 0.0)
            ))

    # ── Inferencia ────────────────────────────
    def predict(self, x: np.ndarray) -> np.ndarray:
        out = x
        for layer in self.layers:
            out = layer.forward(out, training=False)
        return out

    # ── Entrenamiento (un batch) ──────────────
    def train_step(self, x: np.ndarray, y: np.ndarray) -> float:
        # Forward
        out = x
        for layer in self.layers:
            out = layer.forward(out, training=True)

        # MSE loss
        diff = out - y
        loss = float(np.mean(diff ** 2))
        self.loss_history.append(loss)
        if len(self.loss_history) > 10_000:
            self.loss_history = self.loss_history[-5_000:]

        # Backward
        grad = 2 * diff / diff.size
        for layer in reversed(self.layers):
            grad = layer.backward(grad, lr=self.lr)

        return loss

    # ── Serialización ─────────────────────────
    def save(self, path: str):
        state = {
            'layers': [l.get_state() for l in self.layers],
            'lr': self.lr,
            'loss_history': self.loss_history[-200:]
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump(state, f)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'rb') as f:
                state = pickle.load(f)
            for i, layer_state in enumerate(state['layers']):
                if i < len(self.layers):
                    self.layers[i].set_state(layer_state)
            self.lr = state.get('lr', self.lr)
            self.loss_history = state.get('loss_history', [])
            return True
        except Exception as e:
            print(f"[NeuralNet] Error cargando: {e}", flush=True)
            return False

    def avg_recent_loss(self, n: int = 100) -> float:
        if not self.loss_history:
            return 1.0
        return float(np.mean(self.loss_history[-n:]))
