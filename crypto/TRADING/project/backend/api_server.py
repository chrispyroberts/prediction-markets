# api_server.py -- FastAPI entrypoint for DataHub state and health
# The FastAPI app is created via create_app(datahub_instance), which must be called with a DataHub instance from main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import asyncio

# Do not instantiate DataHub here; it will be passed in from main.py

def create_app(datahub_instance):
    app = FastAPI()

    @app.get("/api/state")
    async def get_state():
        state = await datahub_instance.get_all()
        return JSONResponse({k: v.dict() for k, v in state.items()})

    @app.get("/api/health")
    async def get_health():
        health = await datahub_instance.get_health()
        return JSONResponse(health)

    @app.get("/api/history/{feed_name}")
    async def get_history(feed_name: str):
        print(f"API: History requested for feed: {feed_name}")
        history = await datahub_instance.get_history(feed_name)
        print(f"API: Returning {len(history)} history items for {feed_name}")
        return JSONResponse(history)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                state = await datahub_instance.get_all()
                await websocket.send_json({k: v.dict() for k, v in state.items()})
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            pass

    return app 