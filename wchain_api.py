import requests
import time
from typing import Dict, Optional, Tuple, List
from config import (
    WCO_PRICE_API,
    WAVE_PRICE_API,
    WCO_SUPPLY_API,
    HOLDERS_API,
    OG88_PRICE_API,
    OG88_COUNTERS_API,
    WAVE_COUNTERS_API,
    CACHE_TTL,
    PRICE_CACHE_TTL,
    BLOCKSCOUT_API_BASE,
    OG88_TOKEN_ADDRESS,
    BURN_WALLET_ADDRESS,
)

class WChainAPI:
    def __init__(self):
        self.price_cache = {}
        self.supply_cache = {}
        self.holders_cache = {}
        self.cache_timestamps = {}
    
    def _is_cache_valid(self, cache_key: str, ttl: int) -> bool:
        """Check if cached data is still valid"""
        if cache_key not in self.cache_timestamps:
            return False
        return time.time() - self.cache_timestamps[cache_key] < ttl
    
    def _update_cache(self, cache_key: str, data: Dict, ttl: int):
        """Update cache with new data"""
        if cache_key == "price":
            self.price_cache = data
        elif cache_key == "supply":
            self.supply_cache = data
        elif cache_key == "holders":
            self.holders_cache = data
        
        self.cache_timestamps[cache_key] = time.time()
    
    def get_wco_price(self) -> Optional[Dict]:
        """Get WCO token price and 24h change"""
        cache_key = "wco_price"
        
        if self._is_cache_valid(cache_key, PRICE_CACHE_TTL):
            cached_data = self.price_cache.get("wco")
            if cached_data:
                return cached_data
        
        try:
            response = requests.get(WCO_PRICE_API, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Store in cache
            if "wco" not in self.price_cache:
                self.price_cache["wco"] = {}
            self.price_cache["wco"] = data
            self.cache_timestamps[cache_key] = time.time()
            
            return data
        except requests.RequestException as e:
            print(f"Error fetching WCO price: {e}")
            return None
    
    def get_wave_price(self) -> Optional[Dict]:
        """Get WAVE token price"""
        cache_key = "wave_price"
        
        if self._is_cache_valid(cache_key, PRICE_CACHE_TTL):
            cached_data = self.price_cache.get("wave")
            if cached_data:
                return cached_data
        
        try:
            response = requests.get(WAVE_PRICE_API, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Store in cache
            if "wave" not in self.price_cache:
                self.price_cache["wave"] = {}
            self.price_cache["wave"] = data
            self.cache_timestamps[cache_key] = time.time()
            
            return data
        except requests.RequestException as e:
            print(f"Error fetching WAVE price: {e}")
            return None
    
    def get_og88_price(self) -> Optional[Dict]:
        """Get OG88 token price and market data"""
        cache_key = "og88_price"
        
        if self._is_cache_valid(cache_key, PRICE_CACHE_TTL):
            cached_data = self.price_cache.get("og88")
            if cached_data:
                return cached_data
        
        try:
            response = requests.get(OG88_PRICE_API, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Store in cache
            if "og88" not in self.price_cache:
                self.price_cache["og88"] = {}
            self.price_cache["og88"] = data
            self.cache_timestamps[cache_key] = time.time()
            
            return data
        except requests.RequestException as e:
            print(f"Error fetching OG88 price: {e}")
            return None
    
    def get_og88_counters(self) -> Optional[Dict]:
        """Get OG88 token holders count and transfers count"""
        cache_key = "og88_counters"
        
        if self._is_cache_valid(cache_key, CACHE_TTL):
            cached_data = self.price_cache.get("og88_counters")
            if cached_data:
                return cached_data
        
        try:
            response = requests.get(OG88_COUNTERS_API, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Store in cache
            if "og88_counters" not in self.price_cache:
                self.price_cache["og88_counters"] = {}
            self.price_cache["og88_counters"] = data
            self.cache_timestamps[cache_key] = time.time()
            
            return data
        except requests.RequestException as e:
            print(f"Error fetching OG88 counters: {e}")
            return None
    
    def get_wave_counters(self) -> Optional[Dict]:
        """Get WAVE token holders count and transfers count"""
        cache_key = "wave_counters"
        
        if self._is_cache_valid(cache_key, CACHE_TTL):
            cached_data = self.price_cache.get("wave_counters")
            if cached_data:
                return cached_data
        
        try:
            response = requests.get(WAVE_COUNTERS_API, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Store in cache
            if "wave_counters" not in self.price_cache:
                self.price_cache["wave_counters"] = {}
            self.price_cache["wave_counters"] = data
            self.cache_timestamps[cache_key] = time.time()
            
            return data
        except requests.RequestException as e:
            print(f"Error fetching WAVE counters: {e}")
            return None
    
    def get_wco_supply_info(self) -> Optional[Dict]:
        """Get WCO supply information including circulating supply, burned tokens, etc."""
        cache_key = "supply"
        
        if self._is_cache_valid(cache_key, CACHE_TTL):
            return self.supply_cache
        
        try:
            response = requests.get(WCO_SUPPLY_API, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Store in cache
            self.supply_cache = data
            self.cache_timestamps[cache_key] = time.time()
            
            return data
        except requests.RequestException as e:
            print(f"Error fetching WCO supply info: {e}")
            return None
    
    def get_holders_count(self) -> Optional[int]:
        """Get the number of WCO holders - placeholder for future implementation"""
        # Placeholder for future holders functionality
        return None
    
    def get_market_cap(self) -> Optional[float]:
        """Calculate market cap using price and circulating supply"""
        price_data = self.get_wco_price()
        supply_data = self.get_wco_supply_info()
        
        if not price_data or not supply_data:
            return None
        
        try:
            price = price_data.get('price', 0)
            circulating_supply = float(supply_data.get('summary', {}).get('circulating_supply_wco', 0))
            market_cap = price * circulating_supply
            return market_cap
        except (ValueError, TypeError) as e:
            print(f"Error calculating market cap: {e}")
            return None
    
    def get_comprehensive_info(self) -> Dict:
        """Get all available W-Chain information"""
        info = {
            'wco_price': self.get_wco_price(),
            'wave_price': self.get_wave_price(),
            'og88_price': self.get_og88_price(),
            'supply_info': self.get_wco_supply_info(),
            'market_cap': self.get_market_cap()
        }
        return info

    def get_address_token_transfers(self, address: str, limit: int = 10) -> Optional[List[Dict]]:
        """Fetch recent token transfers for a specific address from the explorer API."""
        normalized_address = address.lower()
        url = f"{BLOCKSCOUT_API_BASE}/addresses/{normalized_address}/token-transfers"
        params = {
            "type": "TOKEN",
            "items_count": limit
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('items', [])
        except requests.RequestException as exc:
            print(f"Error fetching token transfers for {address}: {exc}")
            return None

    def get_recent_og88_burns(self, limit: int = 5) -> Optional[List[Dict]]:
        """Return the most recent OG88 transfers sent to the burn wallet."""
        transfers = self.get_address_token_transfers(BURN_WALLET_ADDRESS, limit=limit)
        if transfers is None:
            return None
        og88_transfers = [
            tx for tx in transfers
            if tx.get('token', {}).get('address', '').lower() == OG88_TOKEN_ADDRESS
        ]
        return og88_transfers or []
