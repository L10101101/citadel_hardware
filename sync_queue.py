import threading

from datetime import datetime
from queue import Queue, Empty
from typing import Optional

class SyncQueue:
    def __init__(self):
        self.queue = Queue()
        self.lock = threading.Lock()
    
    def add(self, operation_type: str, data: dict):
        with self.lock:
            self.queue.put({
                'type': operation_type,
                'data': data,
                'timestamp': datetime.now(),
                'retry_count': 0
            })
    
    def get(self, timeout: Optional[float] = None):
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None
    
    def size(self):
        return self.queue.qsize()