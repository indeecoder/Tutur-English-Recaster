import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, HTTPException, Query, Depends, Security
from fastapi.responses import FileResponse, JSONResponse

# from fastapi.security import APIKeyHeader
from src.stream_utils.stream_engine import stream, refresh_server_rtc_config
from src.stream_utils.turn_creds import get_turn_creds

# from src.secrets import api_name, api_key

logger = logging.getLogger(__name__)

RENEW_INTERVAL_S = 3000


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await refresh_server_rtc_config()
    except Exception:
        logger.exception("initial server rtc config fetch failed")

    async def renew():
        while True:
            await asyncio.sleep(RENEW_INTERVAL_S)
            try:
                await refresh_server_rtc_config()
            except Exception:
                logger.exception("server rtc config renew failed")

    task = asyncio.create_task(renew())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


# async def verify_api_key(key: str = Security(APIKeyHeader(name=api_name, auto_error=False))):
#     if key is None:
#         raise HTTPException(status_code=401, detail="Missing API key")
#     if key != api_key:
#         raise HTTPException(status_code=403, detail="Invalid API key")


app = FastAPI(
    # title="Tutur API Document",
    # version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
    # dependencies=[Depends(verify_api_key)],
)

stream.mount(app)


@app.get("/rtc-config")
async def rtc_config_for_client():
    """Get short-lived TURN credentials for the client.

    Fetches ICE server configuration (STUN/TURN) so the browser can relay media
    traffic when connections are blocked by NAT/firewall.

    Returns: A JSON object containing `iceServers` ready to be passed
    to `RTCPeerConnection`.

    Example: `{"iceServers": [{"urls": "turn:...", "username": "...", "credential": "..."}]}`

    > Sent with `Cache-Control: no-store` — credentials are short-lived.
    """
    try:
        data = await get_turn_creds()

    except Exception:
        logger.exception("failed to fetch client TURN creds")
        raise HTTPException(status_code=502, detail="TURN credentials unavailable")

    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@app.get("/outputs")
async def get_outputs(webrtc_id: str = Query(..., description="The WebRTC connection ID used during the offer")):
    """Fetch the latest `AdditionalOutputs` for a WebRTC connection.

    fastrtc does not send output payloads over the datachannel — it only sends
    a `{"type": "fetch_output"}` signal. The payload is stored in the server's
    per-connection output queue and must be fetched here.

    Client flow: datachannel message `fetch_output` -> `GET /outputs?webrtc_id=...`.

    Returns: list of args passed to `AdditionalOutputs`, e.g.
    `[{"you": "...", "native": "..."}]`.

    Waits up to ~10s (fastrtc internal timeout); returns 504 on timeout.
    """
    try:
        outputs = await stream.fetch_latest_output(webrtc_id)

    except TimeoutError:
        raise HTTPException(status_code=504, detail="Timed out waiting for output")

    except Exception:
        logger.exception("failed to fetch outputs for %s", webrtc_id)
        raise HTTPException(status_code=500, detail="Failed to fetch outputs")

    return JSONResponse(list(outputs.args), headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(Path(__file__).resolve().parent / "templates" / "index.html")
