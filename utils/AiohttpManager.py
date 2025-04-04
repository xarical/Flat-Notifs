import asyncio
from typing import Optional

import aiohttp

import utils.config as config
import utils.helpers as helpers


class AiohttpManager:
    """
    The AiohttpManager class manages the aiohttp session.
    """

    def __init__(self):
        """
        Initialize the aiohttp manager.
        """
        self._session = None
        self._semaphore = asyncio.Semaphore(config.max_api_load) # Cap API load

    async def refresh_session(self) -> None:
        """
        Refresh the aiohttp session, or 
        create it if it doesn't exist yet.
        """
        await self.close_session()
        self._session = aiohttp.ClientSession()
        helpers.log("Aiohttp session created.")

    async def close_session(self) -> None:
        """
        Close the aiohttp session.
        """
        if self._session:
            await self._session.close()
            helpers.log("Aiohttp session closed.")

    async def read_api(self, url: str, api_key: Optional[str] = None) -> list[dict]:
        """
        Get the contents of the api using aiohttp.
        Ignores fail status codes other than 401.
        """
        if not self._session:
            raise ValueError("Session not initialized")

        try:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
            async with self._semaphore:
                async with self._session.get(url, headers=headers) as response:
                    if response.status == 401: # invalid API key
                        try:
                            response.raise_for_status() # force an exception to get e
                        except aiohttp.ClientResponseError as e:
                            helpers.log("401 - Unauthorized:", e)
                        return [] # empty dict will inform the user that their notifications could not be read
                    
                    response.raise_for_status()
                    resp_headers = response.headers
                    import time
                    helpers.log(f"Rate limit remaining for key {api_key[-4:]}: {resp_headers.get('X-RateLimit-Remaining')}/{resp_headers.get('X-RateLimit-Limit')}, resets in {((int(resp_headers.get('X-RateLimit-Reset')) - time.time())/60):.2f} minutes") # DEBUG
                    return await response.json()

        except aiohttp.ClientError as e: # ignore edge case http codes
            raise Exception("API request error (do not act):", e)