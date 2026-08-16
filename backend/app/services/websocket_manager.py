import asyncio
import json
import logging
import uuid
import time
from typing import Dict, List, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Format: { "client_id": {"ws": WebSocket, "role": "AUTHORITY|CITIZEN", "zone_id": int_or_None} }
        self.active_connections: Dict[str, Dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket, client_id: str, role: str, zone_id: int = None):
        await websocket.accept()
        self.active_connections[client_id] = {
            "ws": websocket,
            "role": role.upper(),
            "zone_id": zone_id
        }
        logger.info(f"Client {client_id} connected. Role: {role}, Zone: {zone_id}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"Client {client_id} disconnected.")

    def _build_envelope(self, event_type: str, payload: dict) -> dict:
        return {
            "event_type": event_type,
            "event_id": str(uuid.uuid4()),
            "timestamp": int(time.time()),
            "payload": payload
        }

    async def _send_to_client(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            ws = self.active_connections[client_id]["ws"]
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send to {client_id}: {e}")
                self.disconnect(client_id)

    async def broadcast_authority(self, event_type: str, payload: dict):
        """Broadcast an event to ALL active Authority dashboards."""
        message = self._build_envelope(event_type, payload)
        tasks = []
        for client_id, data in self.active_connections.items():
            if data["role"] == "AUTHORITY":
                tasks.append(self._send_to_client(client_id, message))
        if tasks:
            await asyncio.gather(*tasks)

    async def broadcast_citizen_zone(self, zone_id: int, event_type: str, payload: dict):
        """Broadcast an event ONLY to Citizens currently located in the targeted zone_id."""
        message = self._build_envelope(event_type, payload)
        tasks = []
        for client_id, data in self.active_connections.items():
            if data["role"] == "CITIZEN" and data["zone_id"] == zone_id:
                tasks.append(self._send_to_client(client_id, message))
        if tasks:
            await asyncio.gather(*tasks)

# Global manager instance
manager = ConnectionManager()
