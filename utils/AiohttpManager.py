import aiohttp

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

    async def read_api(self, url: str, api_key: str) -> list[dict]:
        """
        Get the contents of the api using aiohttp.
        Ignores fail status codes other than 401.
        """
        if not self._session:
            raise ValueError("Session not initialized")

        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            async with self._session.get(url, headers=headers) as response:
                if response.status == 401: # invalid API key
                    try:
                        response.raise_for_status() # force an exception to get e
                    except aiohttp.ClientResponseError as e:
                        helpers.log("401 - Unauthorized:", e)
                    return [] # empty dict will inform the user that their notifications could not be read
                
                response.raise_for_status()
                return await response.json()

        except aiohttp.ClientError as e: # ignore edge case http codes
            raise Exception("API request error (do not act):", e)