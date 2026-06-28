import hashlib
import hmac
import struct
import logging
import re

logger = logging.getLogger(__name__)

class HashAnalyzer:
    def __init__(self):
        self.verified_rounds = 0

    def crash_point_from_seed(self, server_seed, client_seed, nonce):
        """Calculate Aviator crash point from server+client seeds"""
        try:
            hmac_key = server_seed.encode() if isinstance(server_seed, str) else server_seed
            message = f"{client_seed}:{nonce}".encode() if isinstance(client_seed, str) else f"{client_seed}:{nonce}".encode()
            
            result = hmac.new(hmac_key, message, hashlib.sha256).hexdigest()
            
            # First 4 bytes
            h = int(result[:8], 16)
            
            # Crash point formula: floor(2^32 / (h + 1)) * (1 - 0.01)
            e = 2**32 / (h + 1)
            crash_point = int(e * 100) / 100
            crash_point = max(1.0, crash_point)
            
            return crash_point
        except Exception as e:
            logger.error(f"Crash point calc error: {e}")
            return None

    def verify_hash_chain(self, hashes):
        """Verify SHA-256 hash chain integrity"""
        results = []
        for i in range(len(hashes) - 1):
            current = hashes[i].get('hash', '')
            next_hash = hashes[i + 1].get('hash', '')
            
            # Verify: SHA256(current) should equal next_hash
            expected = hashlib.sha256(current.encode()).hexdigest() if isinstance(current, str) else hashlib.sha256(current).hexdigest()
            
            if expected == next_hash:
                results.append(True)
            else:
                results.append(False)
        
        return results

    def analyze_seed_chain(self, seed_data):
        """Full analysis of seed chain"""
        result = {
            "total_rounds": len(seed_data),
            "verified_rounds": 0,
            "failed_rounds": 0,
            "anomalies": []
        }

        for i, item in enumerate(seed_data):
            server_seed = item.get('server_seed', '')
            client_seed = item.get('client_seed', '')
            nonce = item.get('nonce', 0)
            actual_crash = item.get('crash_multiplier', 0)

            if server_seed and client_seed:
                expected = self.crash_point_from_seed(server_seed, client_seed, nonce)
                if expected and actual_crash:
                    if abs(expected - actual_crash) < 0.1:
                        result["verified_rounds"] += 1
                    else:
                        result["failed_rounds"] += 1
                        result["anomalies"].append({
                            "round": i,
                            "expected": expected,
                            "actual": actual_crash
                        })

        return result

    def detect_patterns(self, multipliers, window=20):
        """Detect patterns in crash multiplier history"""
        if len(multipliers) < window:
            return {}

        patterns = {}
        
        # Recent average
        patterns['recent_avg'] = sum(multipliers[-window:]) / window
        
        # Running variance
        avg = patterns['recent_avg']
        variance = sum((m - avg) ** 2 for m in multipliers[-window:]) / window
        patterns['variance'] = variance
        
        # Low multiplier streak
        low_count = sum(1 for m in multipliers[-window:] if m < 2.0)
        patterns['low_streak'] = low_count / window
        
        # High multiplier frequency
        high_count = sum(1 for m in multipliers[-window:] if m > 5.0)
        patterns['high_freq'] = high_count / window
        
        # Trend (are recent rounds higher or lower?)
        first_half = sum(multipliers[-window:-window//2]) / (window//2)
        second_half = sum(multipliers[-window//2:]) / (window//2)
        patterns['trend'] = 'up' if second_half > first_half else 'down'
        patterns['trend_magnitude'] = abs(second_half - first_half)

        return patterns
