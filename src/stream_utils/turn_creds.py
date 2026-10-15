import httpx
from src.secrets import turn_url, turn_token


async def get_turn_creds(ttl: int = 300):
    async with httpx.AsyncClient() as aclient:
        resp = await aclient.get(
            turn_url,
            headers={"Authorization": f"Bearer {turn_token}"},
            params={"ttl": ttl},
        )
        resp.raise_for_status()
        return resp.json()
