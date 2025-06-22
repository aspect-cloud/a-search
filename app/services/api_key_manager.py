import logging
import time
import threading
from contextlib import contextmanager
from typing import Optional, List, Dict, Tuple

from google.api_core import exceptions as google_exceptions



class ApiKeyManager:

    def __init__(self, api_keys: List[str], cooldown_seconds: int = 60):
        if not api_keys:
            raise ValueError("No API keys provided.")
        
        self.keys: Dict[str, Dict] = {
            key: {
                "available_at": 0,
                "failed": False
            }
            for key in api_keys
        }
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._key_indices = list(self.keys.keys())
        self._current_index = 0
        logging.info(f"Initialized ApiKeyManager with {len(self.keys)} keys.")

    def get_key(self, peek: bool = False) -> Optional[str]:
        """
        Retrieves an available API key.

        Args:
            peek (bool): If True, returns an available key without marking it as 'in-use'
                         or advancing the key rotation index. Defaults to False.

        Returns:
            Optional[str]: An available API key, or None if all keys are on cooldown or failed.
        """
        with self._lock:
            start_index = self._current_index
            temp_index = self._current_index

            for _ in range(len(self._key_indices)):
                key = self._key_indices[temp_index]
                key_info = self.keys[key]

                if not key_info["failed"] and time.time() >= key_info["available_at"]:
                    if not peek:
                        # If not peeking, advance the main index for the next call
                        self._current_index = (temp_index + 1) % len(self._key_indices)
                        logging.info(f"Returning available key ...{key[-4:]} for use.")
                    else:
                        logging.info(f"Peeking at available key ...{key[-4:]}.")
                    return key

                # Move to the next key to check
                temp_index = (temp_index + 1) % len(self._key_indices)

            logging.error("All API keys are either on cooldown or have failed.")
            return None

    def report_failure(self, api_key: str, is_rate_limit: bool = True):
        with self._lock:
            if api_key in self.keys:
                if is_rate_limit:
                    self.keys[api_key]["available_at"] = time.time() + self.cooldown_seconds
                    logging.warning(f"API key ...{api_key[-4:]} was rate-limited. On cooldown for {self.cooldown_seconds}s.")
                else:
                    self.keys[api_key]["failed"] = True
                    logging.error(f"API key ...{api_key[-4:]} has been marked as permanently failed.")

    def release_key(self, api_key: str):
        with self._lock:
            if api_key in self.keys:
                self.keys[api_key]["available_at"] = 0
                logging.info(f"API key ...{api_key[-4:]} was released from cooldown after successful use.")

    @contextmanager
    def get_key_for_session(self):
        """
        A context manager to provide a single API key for the duration of a session.
        Handles key release and failure reporting automatically.
        """
        key = self.get_key()
        if not key:
            raise RuntimeError("Could not acquire an API key for the session.")

        try:
            yield key
            # If the block completes without error, release the key for immediate reuse.
            self.release_key(key)
        except google_exceptions.PermissionDenied as e:
            logging.error(f"Permanent failure (Permission Denied) for key ...{key[-4:]}. Marking as failed.")
            self.report_failure(key, is_rate_limit=False)
            raise e
        except google_exceptions.ResourceExhausted as e:
            logging.warning(f"Rate limit hit for key ...{key[-4:]}. Putting on cooldown.")
            self.report_failure(key, is_rate_limit=True)
            raise e
        except Exception as e:
            logging.error(f"An unexpected error occurred with key ...{key[-4:]}. Putting on cooldown as a precaution.")
            self.report_failure(key, is_rate_limit=True)
            raise e







_api_key_manager_instance: Optional[ApiKeyManager] = None
_manager_lock = threading.Lock()

def initialize_api_key_manager(api_keys: List[str]):
    global _api_key_manager_instance
    with _manager_lock:
        if _api_key_manager_instance is None:
            _api_key_manager_instance = ApiKeyManager(api_keys)
        else:
            logging.warning("API Key Manager is already initialized.")

def get_api_key_manager() -> ApiKeyManager:
    if _api_key_manager_instance is None:
        raise RuntimeError("API Key Manager has not been initialized. Call initialize_api_key_manager() first.")
    return _api_key_manager_instance
