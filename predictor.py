import os
import warnings
import json
import random
from typing import List, Dict
from datetime import datetime
from collections import deque
import math

warnings.filterwarnings('ignore')


class MultiModelPredictor:
    """
    Lightweight statistical predictor — no ML dependencies needed.
    Uses probability distribution analysis + pattern recognition.
    """

    def __init__(self, sequence_length=20, model_dir="model"):
        self.sequence_length = sequence_length
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)

        self.is_trained = True
        self.theoretical_mean = 1.97
        self.house_edge = 0.03

    def _calc_mean(self, arr):
        return sum(arr) / len(arr) if arr else 0

    def _calc_std(self, arr):
        if len(arr) < 2:
            return 0
        mean = self._calc_mean(arr)
        variance = sum((x - mean) ** 2 for x in arr) / (len(arr) - 1)
        return math.sqrt(variance)

    def _calc_median(self, arr):
        sorted_arr = sorted(arr)
        n = len(sorted_arr)
        if n % 2 == 0:
            return (sorted_arr[n // 2 - 1] + sorted_arr[n // 2]) / 2
        return sorted_arr[n // 2]

    def generate_signal(self, history):
        if len(history) < self.sequence_length:
            return {
                "signal": "WAIT",
                "reason": f"Need {self.sequence_length} rounds, have {len(history)}",
                "confidence": 0,
                "prediction": None,
                "suggested_cashout": None,
                "timestamp": datetime.now().isoformat(),
            }

        arr = history[-self.sequence_length:]
        recent_20 = history[-20:] if len(history) >= 20 else history

        # Basic statistics
        recent_mean = self._calc_mean(recent_20)
        recent_std = self._calc_std(recent_20)
        recent_median = self._calc_median(recent_20)

        # Streak analysis
        high_streak = sum(1 for x in history[-10:] if x >= 2.0)
        low_streak = sum(1 for x in history[-10:] if x < 1.5)
        very_high = sum(1 for x in history[-20:] if x >= 5.0)

        # Mean reversion prediction
        stat_pred = recent_mean * 0.6 + self.theoretical_mean * 0.4
        if high_crashes := sum(1 for x in arr if x >= 3.0) >= 3:
            stat_pred *= 0.85
        if sum(1 for x in arr if x < 1.5) >= 4:
            stat_pred *= 1.15

        predicted = max(1.0, stat_pred)

        # Confidence based on volatility and data amount
        vol_factor = max(0, 1.0 - (recent_std / max(recent_mean, 0.1)) * 0.5)
        data_factor = min(1.0, len(history) / 100)
        confidence = round(min(0.95, vol_factor * data_factor), 3)

        # Generate signal
        signal = "SKIP"
        reason = "Conservative — confidence too low"
        suggested_cashout = None

        if confidence >= 0.50:
            if predicted >= 5.0:
                signal = "BUY_HIGH"
                suggested_cashout = min(predicted, 10.0)
                reason = f"High multiplier pattern detected ({predicted:.2f}x)"
            elif predicted >= 2.5:
                signal = "BUY_MEDIUM"
                suggested_cashout = min(predicted, 5.0)
                reason = f"Medium multiplier expected ({predicted:.2f}x)"
            elif predicted >= 1.5:
                signal = "BUY_LOW"
                suggested_cashout = min(predicted, 2.0)
                reason = f"Low multiplier expected ({predicted:.2f}x)"
            elif predicted < 1.5:
                signal = "DANGER"
                suggested_cashout = 1.2
                reason = f"Early crash predicted ({predicted:.2f}x) — high risk"

        # Override based on streak analysis
        if high_streak >= 7:
            signal = "CAUTION"
            reason = "7+ high rounds recently — correction likely soon"
            suggested_cashout = 1.5
        elif low_streak >= 6 and predicted >= 2.0:
            signal = "OPPORTUNITY"
            reason = "6+ low rounds — statistical bounce expected"
            suggested_cashout = min(predicted * 1.2, 5.0)
        elif very_high >= 2 and predicted < 3.0:
            signal = "AVOID"
            reason = "Multiple 5x+ recently — volatility too high"
            suggested_cashout = None

        return {
            "signal": signal,
            "reason": reason,
            "prediction": round(predicted, 2),
            "confidence": round(confidence, 3),
            "suggested_cashout": suggested_cashout,
            "timestamp": datetime.now().isoformat(),
            "model_count": 1,
            "stats": {
                "mean_20": round(recent_mean, 2),
                "std_20": round(recent_std, 2),
                "high_streak": high_streak,
                "low_streak": low_streak,
            }
        }

    def train(self, history, epochs=0):
        """No training needed — statistical model only"""
        if len(history) >= 20:
            self.is_trained = True
            print(f"[✓] Statistical model ready with {len(history)} data points")
            return True
        return False

    def save(self, path=None):
        pass

    def load(self, path=None):
        self.is_trained = True
