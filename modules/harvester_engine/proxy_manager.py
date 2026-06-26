"""V1.5.3 代理管理器"""
import random
import time

class ProxyManager:
    def __init__(self, proxy_list=None):
        self._proxies = proxy_list or []
        self._index = 0
        self._cooldowns = {}

    def add_proxy(self, proxy_url):
        if proxy_url not in self._proxies:
            self._proxies.append(proxy_url)

    def get_proxy(self):
        available = [p for p in self._proxies if time.time() > self._cooldowns.get(p, 0)]
        if not available:
            return None
        proxy = random.choice(available)
        return proxy

    def mark_failed(self, proxy_url, cooldown_seconds=300):
        self._cooldowns[proxy_url] = time.time() + cooldown_seconds

    @property
    def pool_size(self):
        return len(self._proxies)
