"""
SHA-256 and SHA-512 hash analyzer for Spribe Aviator.
Converts hashes to crash multipliers and analyzes seed chains.
"""
import hashlib
import hmac
import struct
import json
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime


class SpribeHashAnalyzer:
    """
    Analyzes Spribe's provably fair hash system for Aviator.
    
    Spribe Aviator crash multiplier formula:
    1. Combine: server_seed + client_seed1 + client_seed2 + client_seed3
    2. Hash with SHA-512
    3. Take first 13 hex characters of the digest
    4. Convert hex to decimal, divide by 16^13 to get fraction h
    5. crash = (100 - house_edge) / (100 * (1 - h))
       where house_edge = 3 (3%)
    
    Alternative (older) SHA-256 method:
    1. HMAC-SHA256(key=server_seed, message=client_seed:nonce:0)
    2. Take first 8 hex chars, convert to 32-bit int
    3. crash = max(1, (2^32 / (int + 1)) * (1 - house_edge))
    """
    
    def __init__(self):
        self.house_edge = 0.03  # 3%
        self.known_seeds = {}
        self.pattern_cache = {}
    
    def sha512_to_crash(self, server_seed: str, client_seeds: List[str]) -> float:
        """
        Convert SHA-512 hash to crash multiplier (Spribe's current method).
        
        Formula: crash = (100 - house_edge) / (100 * (1 - h))
        where h = int(first_13_hex_chars_of_sha512, 16) / 16^13
        """
        # Combine seeds
        combined = server_seed + "".join(client_seeds)
        
        # SHA-512 hash
        hash_bytes = hashlib.sha512(combined.encode()).digest()
        hash_hex = hash_bytes.hex()
        
        # Take first 13 hex characters
        first_13 = hash_hex[:13]
        
        # Convert to decimal
        h_int = int(first_13, 16)
        
        # Maximum value of 13 hex characters is 16^13
        max_val = 16 ** 13
        
        # Get fraction h between 0 and 1
        h = h_int / max_val
        
        # Apply crash formula
        edge = self.house_edge
        crash = (100 - edge * 100) / (100 * (1 - h))
        
        return max(1.0, round(crash, 2))
    
    def sha256_to_crash(self, server_seed: str, client_seed: str, nonce: int = 0) -> float:
        """
        Convert SHA-256 HMAC to crash multiplier (older method, some providers).
        
        Formula: crash = max(1, (2^32 / (int + 1)) * (1 - house_edge))
        """
        # HMAC-SHA256
        message = f"{client_seed}:{nonce}:0"
        hash_bytes = hmac.new(
            server_seed.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        
        # Take first 4 bytes (8 hex chars) as 32-bit integer
        int_val = struct.unpack('>I', hash_bytes[:4])[0]
        
        # Crash formula
        crash = (2**32 / (int_val + 1)) * (1 - self.house_edge)
        
        return max(1.0, round(crash, 2))
    
    def verify_round(self, server_seed: str, client_seeds: List[str], 
                     actual_crash: float) -> Dict:
        """
        Verify if a round was provably fair by recalculating the crash.
        Returns match status and calculated crash.
        """
        calculated = self.sha512_to_crash(server_seed, client_seeds)
        match = abs(calculated - actual_crash) < 0.01
        
        return {
            "verified": match,
            "calculated_crash": calculated,
            "actual_crash": actual_crash,
            "server_seed": server_seed[:20] + "...",
            "match": "✅" if match else "❌",
        }
    
    def analyze_seed_chain(self, seeds: List[Dict]) -> Dict:
        """
        Analyze a chain of server seeds to detect patterns.
        Spribe pre-generates a chain of server seeds where
        each seed's hash is published before it's used.
        """
        results = {
            "total_rounds": len(seeds),
            "verified_rounds": 0,
            "failed_rounds": 0,
            "seed_reuse": False,
            "anomalies": [],
            "crash_distribution": {
                "below_1_5": 0,
                "1_5_to_2": 0,
                "2_to_3": 0,
                "3_to_5": 0,
                "5_to_10": 0,
                "above_10": 0,
            },
            "avg_crash": 0,
            "max_crash": 0,
            "min_crash": 100,
        }
        
        total_mult = 0
        
        for i, seed_data in enumerate(seeds):
            server_seed = seed_data.get("server_seed", "")
            client_seeds = seed_data.get("client_seeds", ["", "", ""])
            actual_crash = seed_data.get("multiplier", 0)
            
            if server_seed and actual_crash > 0:
                calc_crash = self.sha512_to_crash(server_seed, client_seeds)
                match = abs(calc_crash - actual_crash) < 0.05
                
                if match:
                    results["verified_rounds"] += 1
                else:
                    results["failed_rounds"] += 1
                    results["anomalies"].append({
                        "round": i,
                        "expected": calc_crash,
                        "actual": actual_crash,
                        "diff": abs(calc_crash - actual_crash),
                    })
                
                # Distribution
                c = actual_crash
                total_mult += c
                results["max_crash"] = max(results["max_crash"], c)
                results["min_crash"] = min(results["min_crash"], c)
                
                if c < 1.5:
                    results["crash_distribution"]["below_1_5"] += 1
                elif c < 2.0:
                    results["crash_distribution"]["1_5_to_2"] += 1
                elif c < 3.0:
                    results["crash_distribution"]["2_to_3"] += 1
                elif c < 5.0:
                    results["crash_distribution"]["3_to_5"] += 1
                elif c < 10.0:
                    results["crash_distribution"]["5_to_10"] += 1
                else:
                    results["crash_distribution"]["above_10"] += 1
        
        if results["total_rounds"] > 0:
            results["avg_crash"] = round(total_mult / results["total_rounds"], 2)
        
        # Check for seed reuse
        unique_seeds = set(s.get("server_seed", "") for s in seeds if s.get("server_seed"))
        if len(unique_seeds) < len(seeds):
            results["seed_reuse"] = True
            results["anomalies"].append({"type": "seed_reuse", "detail": "Server seeds are being reused"})
        
        return results
    
    def predict_next_crash_statistical(self, history: List[float]) -> Dict:
        """
        Statistical prediction based on historical crash distribution.
        This cannot predict exact crashes but gives probability-weighted estimates.
        """
        if len(history) < 20:
            return {"prediction": None, "confidence": 0}
        
        import math
        n = len(history)
        mean = sum(history) / n
        variance = sum((x - mean) ** 2 for x in history) / (n - 1)
        std = math.sqrt(variance)
        
        # Sort for percentiles
        sorted_h = sorted(history)
        
        # Check recent streak
        recent_10 = history[-10:]
        recent_mean = sum(recent_10) / 10
        recent_high = sum(1 for x in recent_10 if x >= 2.0)
        recent_low = sum(1 for x in recent_10 if x < 1.5)
        
        # Mean reversion prediction
        theoretical_mean = 1.97
        reversion_strength = min(0.7, std / 2.0)
        
        if recent_high >= 6:
            # Correction expected
            predicted = recent_mean * 0.75 + theoretical_mean * 0.25
            confidence = min(0.80, 0.5 + recent_high * 0.05)
            reason = f"Correction expected after {recent_high} high rounds"
        elif recent_low >= 5:
            # Bounce expected
            predicted = recent_mean * 0.6 + theoretical_mean * 0.4
            predicted *= 1.15
            confidence = min(0.80, 0.5 + recent_low * 0.05)
            reason = f"Bounce expected after {recent_low} low rounds"
        else:
            # Normal mean reversion
            predicted = recent_mean * (1 - reversion_strength) + theoretical_mean * reversion_strength
            confidence = 0.5 + reversion_strength * 0.2
            reason = "Statistical mean reversion"
        
        predicted = max(1.01, min(100.0, predicted))
        
        # Calculate volatility-based confidence adjustment
        vol_ratio = std / mean if mean > 0 else 0
        confidence *= max(0.5, 1.0 - vol_ratio * 0.3)
        
        return {
            "prediction": round(predicted, 2),
            "confidence": round(min(0.95, confidence), 3),
            "reason": reason,
            "stats": {
                "mean": round(mean, 2),
                "std": round(std, 2),
                "recent_mean": round(recent_mean, 2),
                "recent_high_streak": recent_high,
                "recent_low_streak": recent_low,
            }
        }
    
    def analyze_10000_rounds(self, rounds_data: List[Dict]) -> Dict:
        """
        Deep analysis of 10,000+ rounds to find exploitable patterns.
        """
        analysis = {
            "total_rounds": len(rounds_data),
            "verified_fair": 0,
            "anomalies_found": 0,
            "patterns": {},
            "best_strategy": {},
        }
        
        if not rounds_data:
            return analysis
        
        # Extract multipliers
        multipliers = []
        for r in rounds_data:
            m = r.get("multiplier") or r.get("value") or r.get("crash") or r.get("result")
            if m:
                multipliers.append(float(m))
        
        if not multipliers:
            return analysis
        
        analysis["total_multipliers"] = len(multipliers)
        
        # Basic stats
        import math
        n = len(multipliers)
        mean = sum(multipliers) / n
        median = sorted(multipliers)[n // 2]
        variance = sum((x - mean) ** 2 for x in multipliers) / (n - 1)
        std = math.sqrt(variance)
        
        analysis["statistics"] = {
            "mean": round(mean, 2),
            "median": round(median, 2),
            "std": round(std, 2),
            "max": round(max(multipliers), 2),
            "min": round(min(multipliers), 2),
        }
        
        # Distribution analysis
        dist = {"1.00-1.50": 0, "1.50-2.00": 0, "2.00-3.00": 0, 
                "3.00-5.00": 0, "5.00-10.00": 0, "10.00+": 0}
        for m in multipliers:
            if m < 1.5: dist["1.00-1.50"] += 1
            elif m < 2.0: dist["1.50-2.00"] += 1
            elif m < 3.0: dist["2.00-3.00"] += 1
            elif m < 5.0: dist["3.00-5.00"] += 1
            elif m < 10.0: dist["5.00-10.00"] += 1
            else: dist["10.00+"] += 1
        
        analysis["distribution"] = {k: {"count": v, "pct": f"{v/n*100:.1f}%"} for k, v in dist.items()}
        
        # Streak analysis
        streaks = {"high_2x": [], "low_1_5x": [], "very_high_5x": []}
        current_high = 0
        current_low = 0
        
        for m in multipliers:
            if m >= 2.0:
                current_high += 1
                if current_low > 0:
                    streaks["low_1_5x"].append(current_low)
                    current_low = 0
            elif m < 1.5:
                current_low += 1
                if current_high > 0:
                    streaks["high_2x"].append(current_high)
                    current_high = 0
            else:
                if current_high > 0:
                    streaks["high_2x"].append(current_high)
                    current_high = 0
                if current_low > 0:
                    streaks["low_1_5x"].append(current_low)
                    current_low = 0
        
        # Pattern detection: what happens after N low rounds?
        after_low = {}
        for i in range(len(multipliers) - 5):
            recent = multipliers[i:i+5]
            low_count = sum(1 for x in recent if x < 1.5)
            if low_count >= 3:
                next_round = multipliers[i+5]
                key = f"after_{low_count}_low_in_5"
                if key not in after_low:
                    after_low[key] = []
                after_low[key].append(next_round)
        
        # What happens after N high rounds?
        after_high = {}
        for i in range(len(multipliers) - 5):
            recent = multipliers[i:i+5]
            high_count = sum(1 for x in recent if x >= 2.0)
            if high_count >= 3:
                next_round = multipliers[i+5]
                key = f"after_{high_count}_high_in_5"
                if key not in after_high:
                    after_high[key] = []
                after_high[key].append(next_round)
        
        analysis["patterns"] = {
            "avg_high_streak": round(sum(streaks["high_2x"]) / len(streaks["high_2x"]), 1) if streaks["high_2x"] else 0,
            "max_high_streak": max(streaks["high_2x"]) if streaks["high_2x"] else 0,
            "avg_low_streak": round(sum(streaks["low_1_5x"]) / len(streaks["low_1_5x"]), 1) if streaks["low_1_5x"] else 0,
            "max_low_streak": max(streaks["low_1_5x"]) if streaks["low_1_5x"] else 0,
        }
        
        # Generate best strategy
        strategy = {}
        
        # After low streaks, what's the best cashout?
        for key, vals in after_low.items():
            if vals:
                avg_next = sum(vals) / len(vals)
                strategy[key] = {
                    "count": len(vals),
                    "avg_next_crash": round(avg_next, 2),
                    "recommended_cashout": round(min(avg_next * 0.7, 3.0), 2),
                    "probability_above_2": round(sum(1 for x in vals if x >= 2.0) / len(vals), 3),
                }
        
        for key, vals in after_high.items():
            if vals:
                avg_next = sum(vals) / len(vals)
                strategy[key] = {
                    "count": len(vals),
                    "avg_next_crash": round(avg_next, 2),
                    "recommended_cashout": round(min(avg_next * 0.6, 2.0), 2),
                    "probability_above_2": round(sum(1 for x in vals if x >= 2.0) / len(vals), 3),
                }
        
        analysis["strategy"] = strategy
        
        # Best cashout level
        for cashout in [1.5, 2.0, 3.0, 5.0]:
            wins = sum(1 for m in multipliers if m >= cashout)
            analysis[f"win_rate_{cashout}x"] = f"{wins/n*100:.1f}%"
        
        return analysis
