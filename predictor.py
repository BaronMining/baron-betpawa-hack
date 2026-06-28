"""
Predictor that combines authenticated data extraction with hash analysis.
"""
import os
import warnings
from typing import List, Dict, Optional
from datetime import datetime
from collections import deque

warnings.filterwarnings('ignore')

from hash_analyzer import SpribeHashAnalyzer


class AviatorPredictor:
    """
    Advanced predictor that uses authenticated Betpawa data
    plus Spribe's SHA-512 hash analysis for maximum accuracy.
    """

    def __init__(self):
        self.hash_analyzer = SpribeHashAnalyzer()
        self.is_trained = True
        self.round_history = deque(maxlen=10000)
        self.seed_data = []
        self.deep_analysis = {}
    
    def load_historical_data(self, rounds: List[Dict]):
        """Load 10,000+ rounds for deep analysis"""
        for r in rounds:
            m = r.get("multiplier") or r.get("value") or r.get("crash") or r.get("result")
            if m and float(m) > 0:
                self.round_history.append(float(m))
            
            # Store seed data if available
            if r.get("serverSeed") or r.get("server_seed"):
                self.seed_data.append({
                    "server_seed": r.get("serverSeed") or r.get("server_seed", ""),
                    "client_seeds": [
                        r.get("clientSeed", r.get("client_seed", "")),
                        r.get("clientSeed2", r.get("client_seed_2", "")),
                        r.get("clientSeed3", r.get("client_seed_3", "")),
                    ],
                    "multiplier": float(m) if m else 0,
                })
        
        # Run deep analysis if we have enough data
        count = len(self.round_history)
        if count >= 100:
            print(f"[*] Running deep analysis on {count} rounds...")
            self.deep_analysis = self.hash_analyzer.analyze_10000_rounds(rounds)
            
            # Verify seeds if available
            if self.seed_data:
                seed_analysis = self.hash_analyzer.analyze_seed_chain(self.seed_data)
                self.deep_analysis["seed_verification"] = seed_analysis
    
    def generate_signal(self) -> Dict:
        """Generate the best possible signal using all available data"""
        history = list(self.round_history)
        
        if len(history) < 20:
            return {
                "signal": "WAIT",
                "reason": f"Collecting data ({len(history)}/20 rounds)",
                "confidence": 0,
                "prediction": None,
                "suggested_cashout": None,
                "timestamp": datetime.now().isoformat(),
            }
        
        # Use hash analyzer for prediction
        pred = self.hash_analyzer.predict_next_crash_statistical(history)
        
        predicted = pred.get("prediction")
        confidence = pred.get("confidence", 0)
        reason = pred.get("reason", "Statistical analysis")
        stats = pred.get("stats", {})
        
        # Enhance with deep analysis if available
        strategy = self.deep_analysis.get("strategy", {})
        if strategy:
            # Check current streak conditions
            recent_5 = history[-5:]
            low_in_5 = sum(1 for x in recent_5 if x < 1.5)
            high_in_5 = sum(1 for x in recent_5 if x >= 2.0)
            
            key_low = f"after_{low_in_5}_low_in_5"
            key_high = f"after_{high_in_5}_high_in_5"
            
            if key_low in strategy:
                strat = strategy[key_low]
                if strat["count"] >= 10:
                    # Use the strategy data
                    conf_boost = min(0.15, strat["probability_above_2"] * 0.2)
                    confidence = min(0.95, confidence + conf_boost)
                    if predicted:
                        predicted = round((predicted + strat["avg_next_crash"]) / 2, 2)
                    reason += f" | Pattern: {strat['count']} historical cases"
            
            elif key_high in strategy:
                strat = strategy[key_high]
                if strat["count"] >= 10:
                    reason += f" | Pattern: {strat['count']} historical cases"
        
        # Generate signal type
        signal = "SKIP"
        suggested_cashout = None
        
        if confidence >= 0.50 and predicted:
            if predicted >= 5.0:
                signal = "BUY_HIGH"
                suggested_cashout = min(predicted, 10.0)
            elif predicted >= 2.5:
                signal = "BUY_MEDIUM"
                suggested_cashout = min(predicted, 5.0)
            elif predicted >= 1.5:
                signal = "BUY_LOW"
                suggested_cashout = min(predicted, 2.0)
            elif predicted < 1.5:
                signal = "DANGER"
                suggested_cashout = 1.2
        
        # Apply streak overrides
        if stats.get("recent_high_streak", 0) >= 6 and predicted and predicted < 3.0:
            signal = "CAUTION"
            suggested_cashout = 1.5
            reason = f"Correction after {stats['recent_high_streak']} high rounds"
        elif stats.get("recent_low_streak", 0) >= 5 and predicted and predicted >= 2.0:
            signal = "OPPORTUNITY"
            suggested_cashout = min(predicted * 1.2, 5.0)
            reason = f"Bounce after {stats['recent_low_streak']} low rounds"
        
        return {
            "signal": signal,
            "reason": reason,
            "prediction": predicted,
            "confidence": round(confidence, 3),
            "suggested_cashout": suggested_cashout,
            "timestamp": datetime.now().isoformat(),
            "model_count": 2,
            "data_points": len(history),
            "stats": stats,
        }
    
    def get_analysis_summary(self) -> Dict:
        """Get a summary of the deep analysis"""
        return self.deep_analysis
    
    def train(self, history, epochs=0):
        """No training needed"""
        if len(history) >= 20:
            self.is_trained = True
            return True
        return False
    
    def save(self, path=None):
        pass
    
    def load(self, path=None):
        self.is_trained = True
