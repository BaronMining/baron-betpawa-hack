import numpy as np
import json
import os
import warnings
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from collections import deque
warnings.filterwarnings('ignore')

try:
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    import joblib
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("[!] sklearn not available. Install: pip install scikit-learn")


class MultiModelPredictor:
    """
    Ensemble predictor combining Random Forest, Gradient Boosting, and statistical models.
    """

    def __init__(self, sequence_length=20, model_dir="model"):
        self.sequence_length = sequence_length
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)

        self.rf_model = None
        self.gb_model = None
        self.is_trained = False

        self.theoretical_mean = 1.97
        self.house_edge = 0.03

    def _extract_features(self, history):
        if len(history) < 10:
            return np.array([])

        arr = np.array(history[-self.sequence_length:])
        features = []

        for window in [5, 10, 20]:
            if len(arr) >= window:
                recent = arr[-window:]
                features.extend([
                    np.mean(recent),
                    np.std(recent),
                    np.min(recent),
                    np.max(recent),
                    np.median(recent),
                ])

        if len(arr) >= 5:
            recent_5 = arr[-5:]
            features.append(recent_5[-1] - recent_5[0])
            features.append(np.polyfit(range(len(recent_5)), recent_5, 1)[0])

        high_streak = sum(1 for x in arr[-10:] if x >= 2.0)
        low_streak = sum(1 for x in arr[-10:] if x < 1.5)
        features.append(high_streak / 10)
        features.append(low_streak / 10)

        if len(arr) >= 5:
            returns = np.diff(arr[-10:]) / (arr[-11:-1] + 0.0001) if len(arr) >= 11 else np.diff(arr)
            features.append(np.std(returns) if len(returns) > 0 else 0)

        features.append(np.mean(arr) - self.theoretical_mean)

        if len(arr) >= 5:
            features.append(np.sum(arr[-5:] >= 3.0) / 5)
            features.append(np.sum(arr[-5:] < 1.5) / 5)

        return np.array(features)

    def train(self, history, epochs=30):
        if len(history) < self.sequence_length + 10:
            print(f"[!] Not enough data. Need > {self.sequence_length + 10}, got {len(history)}")
            return False

        arr = np.array(history)

        if ML_AVAILABLE:
            X_features = []
            y_rf = []
            for i in range(self.sequence_length, len(arr)):
                feat = self._extract_features(arr[:i].tolist())
                if len(feat) > 0:
                    X_features.append(feat)
                    y_rf.append(arr[i])

            if len(X_features) > 10:
                X_rf = np.array(X_features)
                y_rf = np.array(y_rf)

                self.rf_model = RandomForestRegressor(
                    n_estimators=200,
                    max_depth=15,
                    min_samples_leaf=3,
                    random_state=42,
                    n_jobs=-1
                )
                self.rf_model.fit(X_rf, y_rf)

                self.gb_model = GradientBoostingRegressor(
                    n_estimators=150,
                    max_depth=8,
                    learning_rate=0.05,
                    random_state=42
                )
                self.gb_model.fit(X_rf, y_rf)
                print(f"[✓] Trained RF & GB on {len(X_rf)} samples")
                self.is_trained = True
                return True

        return False

    def predict_ensemble(self, history):
        if len(history) < self.sequence_length:
            return {"prediction": None, "confidence": 0, "models": 0}

        arr = np.array(history)
        predictions = []
        weights = []

        # 1. Statistical model
        arr_last = arr[-self.sequence_length:]
        recent_mean = np.mean(arr_last)
        stat_pred = recent_mean * 0.6 + self.theoretical_mean * 0.4
        high_crashes = sum(1 for x in arr_last if x >= 3.0)
        if high_crashes >= 3:
            stat_pred *= 0.85
        low_crashes = sum(1 for x in arr_last if x < 1.5)
        if low_crashes >= 4:
            stat_pred *= 1.15
        predictions.append(max(1.0, stat_pred))
        weights.append(0.40)

        # 2. Random Forest
        if self.rf_model is not None:
            feat = self._extract_features(history)
            if len(feat) > 0:
                rf_pred = self.rf_model.predict([feat])[0]
                predictions.append(max(1.0, rf_pred))
                weights.append(0.35)

        # 3. Gradient Boosting
        if self.gb_model is not None:
            feat = self._extract_features(history)
            if len(feat) > 0:
                gb_pred = self.gb_model.predict([feat])[0]
                predictions.append(max(1.0, gb_pred))
                weights.append(0.25)

        if not predictions:
            return {"prediction": None, "confidence": 0, "models": 0}

        weights = np.array(weights)
        weights = weights / weights.sum()
        final_pred = np.average(predictions, weights=weights)

        if len(predictions) >= 2:
            agreement = 1.0 - min(1.0, np.std(predictions) / max(final_pred, 0.1))
        else:
            agreement = 0.5

        model_factor = min(1.0, len(predictions) / 3)
        confidence = agreement * model_factor

        return {
            "prediction": round(float(final_pred), 2),
            "confidence": round(float(confidence), 3),
            "models_used": len(predictions),
            "lower_bound": round(max(1.0, final_pred * 0.7), 2),
            "upper_bound": round(final_pred * 1.3, 2),
        }

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

        pred_result = self.predict_ensemble(history)
        predicted = pred_result.get("prediction")
        confidence = pred_result.get("confidence", 0)

        if predicted is None:
            return {
                "signal": "ERROR",
                "reason": "Model failed to predict",
                "confidence": 0,
                "prediction": None,
                "suggested_cashout": None,
                "timestamp": datetime.now().isoformat(),
            }

        recent = np.array(history[-20:])
        mean_recent = np.mean(recent)
        std_recent = np.std(recent)
        high_streak = sum(1 for x in history[-10:] if x >= 2.0)
        low_streak = sum(1 for x in history[-10:] if x < 1.5)
        very_high = sum(1 for x in history[-20:] if x >= 5.0)

        signal = "SKIP"
        reason = "Conservative — confidence too low"
        suggested_cashout = None

        if confidence >= 0.50:
            if predicted >= 5.0:
                signal = "BUY_HIGH"
                suggested_cashout = min(predicted, 10.0)
                reason = f"High multiplier pattern detected ({predicted}x)"
            elif predicted >= 2.5:
                signal = "BUY_MEDIUM"
                suggested_cashout = min(predicted, 5.0)
                reason = f"Medium multiplier expected ({predicted}x)"
            elif predicted >= 1.5:
                signal = "BUY_LOW"
                suggested_cashout = min(predicted, 2.0)
                reason = f"Low multiplier expected ({predicted}x)"
            elif predicted < 1.5:
                signal = "DANGER"
                suggested_cashout = 1.2
                reason = f"Early crash predicted ({predicted}x) — high risk"

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
            "prediction": predicted,
            "confidence": round(confidence, 3),
            "suggested_cashout": suggested_cashout,
            "timestamp": datetime.now().isoformat(),
            "model_count": pred_result.get("models_used", 0),
            "stats": {
                "mean_20": round(float(mean_recent), 2),
                "std_20": round(float(std_recent), 2),
                "high_streak": high_streak,
                "low_streak": low_streak,
            }
        }

    def save(self, path=None):
        path = path or self.model_dir
        if self.rf_model:
            joblib.dump(self.rf_model, f"{path}/rf_model.pkl")
        if self.gb_model:
            joblib.dump(self.gb_model, f"{path}/gb_model.pkl")
        print(f"[✓] Models saved to {path}")

    def load(self, path=None):
        path = path or self.model_dir
        try:
            rf_path = f"{path}/rf_model.pkl"
            if os.path.exists(rf_path):
                self.rf_model = joblib.load(rf_path)
            gb_path = f"{path}/gb_model.pkl"
            if os.path.exists(gb_path):
                self.gb_model = joblib.load(gb_path)
            self.is_trained = True
            print(f"[✓] Models loaded from {path}")
        except Exception as e:
            print(f"[!] Could not load models: {e}")
