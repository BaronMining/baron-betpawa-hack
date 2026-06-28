import logging
import math
import random
from collections import deque, Counter
from datetime import datetime

from hash_analyzer import HashAnalyzer

logger = logging.getLogger(__name__)

class AviatorPredictor:
    def __init__(self):
        self.round_history = deque(maxlen=20000)
        self.seed_data = deque(maxlen=10000)
        self.hash_analyzer = HashAnalyzer()
        self.pattern_cache = {}
        self.last_analysis = None

    def load_historical_data(self, rounds):
        """Load rounds into history"""
        if isinstance(rounds, list):
            for r in rounds:
                if isinstance(r, dict):
                    mult = r.get('crash_multiplier') or r.get('multiplier') or r.get('crashPoint') or 0
                    nonce = r.get('nonce') or r.get('round') or r.get('id') or 0
                    server_seed = r.get('server_seed', '')
                    client_seed = r.get('client_seed', '')
                    timestamp = r.get('timestamp', datetime.now().isoformat())
                    
                    try:
                        mult = float(mult)
                    except:
                        continue
                    
                    entry = {
                        'crash_multiplier': mult,
                        'nonce': nonce,
                        'server_seed': server_seed,
                        'client_seed': client_seed,
                        'timestamp': timestamp
                    }
                    self.round_history.append(mult)
                    
                    if server_seed:
                        self.seed_data.append(entry)
        
        logger.info(f"Loaded: {len(self.round_history)} multipliers, {len(self.seed_data)} seeds")

    def get_statistics(self):
        """Compute basic statistics"""
        if len(self.round_history) < 2:
            return {}

        m = list(self.round_history)
        n = len(m)

        mean = sum(m) / n
        sorted_m = sorted(m)
        median = sorted_m[n // 2] if n % 2 == 1 else (sorted_m[n//2 - 1] + sorted_m[n//2]) / 2
        variance = sum((x - mean) ** 2 for x in m) / n
        std = math.sqrt(variance)

        return {
            "mean": round(mean, 2),
            "median": round(median, 2),
            "std": round(std, 2),
            "min": round(min(m), 2),
            "max": round(max(m), 2),
            "count": n,
            "recent_mean": round(sum(m[-50:]) / min(50, len(m)), 2) if len(m) >= 10 else 0,
        }

    def get_distribution(self):
        """Get crash point distribution"""
        if not self.round_history:
            return {}

        m = list(self.round_history)
        ranges = {
            "1.0x - 1.5x": 0,
            "1.5x - 2.0x": 0,
            "2.0x - 3.0x": 0,
            "3.0x - 5.0x": 0,
            "5.0x - 10.0x": 0,
            "10.0x+": 0,
        }

        for val in m:
            if val <= 1.5:
                ranges["1.0x - 1.5x"] += 1
            elif val <= 2.0:
                ranges["1.5x - 2.0x"] += 1
            elif val <= 3.0:
                ranges["2.0x - 3.0x"] += 1
            elif val <= 5.0:
                ranges["3.0x - 5.0x"] += 1
            elif val <= 10.0:
                ranges["5.0x - 10.0x"] += 1
            else:
                ranges["10.0x+"] += 1

        total = len(m)
        distribution = {}
        for k, v in ranges.items():
            distribution[k] = {
                "count": v,
                "pct": f"{v/total*100:.1f}%"
            }

        return distribution

    def get_win_rates(self):
        """Calculate win rates at different cashout levels"""
        if not self.round_history:
            return {}

        m = list(self.round_history)
        rates = {}
        for cashout in [1.5, 2.0, 3.0, 5.0]:
            wins = sum(1 for x in m if x >= cashout)
            rates[f"win_rate_{cashout}x"] = f"{wins/len(m)*100:.1f}%" if m else "0%"
        return rates

    def predict_next(self):
        """Predict next crash point using statistical analysis"""
        if len(self.round_history) < 20:
            return None, 0, "Not enough data"

        m = list(self.round_history)
        recent = m[-50:]
        
        # Current stats
        mean_recent = sum(recent) / len(recent)
        std_recent = math.sqrt(sum((x - mean_recent) ** 2 for x in recent) / len(recent))
        
        # Pattern analysis
        low_streak = sum(1 for x in recent if x < 2.0)
        high_in_recent = sum(1 for x in recent if x > 5.0)
        
        # Key insight: after several low rounds, probability of higher round increases
        last_10 = m[-10:]
        all_low = all(x < 2.0 for x in last_10)
        
        # After streak of lows, expect correction
        if all_low and len(last_10) >= 5:
            # Expect a bounce - predict higher than recent mean
            prediction = mean_recent * 1.5 + std_recent
            confidence = min(0.45 + (len([x for x in last_10 if x < 1.5]) * 0.05), 0.85)
            reasoning = "Low streak detected — regression expected"
            signal = "BUY_HIGH"
        elif high_in_recent >= 3:
            # After several highs, expect consolidation
            prediction = mean_recent * 0.7
            confidence = 0.35
            reasoning = "High variance detected — caution advised"
            signal = "CAUTION"
        elif std_recent > 2.0:
            prediction = mean_recent
            confidence = 0.3
            reasoning = "High volatility — unpredictable"
            signal = "SKIP"
        else:
            # Normal state - use recent average
            prediction = mean_recent * (random.uniform(0.85, 1.15))
            confidence = min(0.4 + (low_streak / len(recent)) * 0.2, 0.6)
            reasoning = "Normal pattern — average expected"
            signal = "BUY_MEDIUM" if confidence > 0.35 else "BUY_LOW"

        # Apply confidence threshold
        if confidence < 0.2:
            signal = "SKIP"

        prediction = max(1.0, round(prediction, 2))
        return prediction, confidence, reasoning, signal

    def generate_signal(self):
        """Generate full signal"""
        prediction, confidence, reasoning, signal = self.predict_next()
        
        if prediction is None:
            return {
                "signal": "WAIT",
                "prediction": 1.0,
                "confidence": 0,
                "suggested_cashout": 1.5,
                "reason": reasoning or "Collecting data...",
                "data_points": len(self.round_history),
                "stats": {}
            }

        # Suggested cashout level
        if prediction < 1.5:
            cashout = 1.2
        elif prediction < 2.0:
            cashout = 1.5
        elif prediction < 3.0:
            cashout = 2.0
        elif prediction < 5.0:
            cashout = 3.0
        else:
            cashout = min(prediction * 0.6, 10.0)

        stats = self.get_statistics()
        
        # Recent streak
        m = list(self.round_history)
        recent = m[-10:] if len(m) >= 10 else m
        stats['recent_high_streak'] = sum(1 for x in recent if x > 3.0)
        stats['recent_low_streak'] = sum(1 for x in recent if x < 1.5)

        return {
            "signal": signal,
            "prediction": prediction,
            "confidence": confidence,
            "suggested_cashout": round(cashout, 2),
            "reason": reasoning,
            "data_points": len(self.round_history),
            "stats": stats,
            "timestamp": datetime.now().isoformat()
        }

    def get_analysis_summary(self):
        """Get comprehensive analysis"""
        if not self.round_history:
            return None

        stats = self.get_statistics()
        distribution = self.get_distribution()
        win_rates = self.get_win_rates()
        
        # Strategy analysis
        strategies = {}
        m = list(self.round_history)
        
        # After 1.0x (crash at start)
        after_1 = [m[i+1] for i in range(len(m)-1) if m[i] <= 1.1]
        if after_1:
            strategies["After 1.0x crash"] = {
                "avg_next_crash": f"{sum(after_1)/len(after_1):.2f}x",
                "probability_above_2": f"{sum(1 for x in after_1 if x >= 2.0)/len(after_1)*100:.1f}%",
                "count": len(after_1)
            }
        
        # After high crash (5.0x+)
        after_high = [m[i+1] for i in range(len(m)-1) if m[i] >= 5.0]
        if after_high:
            strategies["After 5.0x+ crash"] = {
                "avg_next_crash": f"{sum(after_high)/len(after_high):.2f}x",
                "probability_above_2": f"{sum(1 for x in after_high if x >= 2.0)/len(after_high)*100:.1f}%",
                "count": len(after_high)
            }

        return {
            "total_multipliers": len(self.round_history),
            "statistics": stats,
            "distribution": distribution,
            "strategy": strategies,
            **win_rates
        }
