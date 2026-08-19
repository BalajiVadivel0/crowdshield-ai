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
        # Format: { "client_id": {"ws": WebSocket, "role": "AUTHORITY|CITIZEN", "event_id": int, "zone_id": int_or_None} }
        self.active_connections: Dict[str, Dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket, client_id: str, role: str, event_id: int, zone_id: int = None):
        await websocket.accept()
        
        # Cleanup stale connection if client_id already exists
        if client_id in self.active_connections:
            old_ws = self.active_connections[client_id]["ws"]
            try:
                await old_ws.close(code=1000, reason="Replaced by new connection")
            except Exception:
                pass
            logger.info(f"Closed stale connection for client {client_id}")
            
        self.active_connections[client_id] = {
            "ws": websocket,
            "role": role.upper(),
            "event_id": event_id,
            "zone_id": zone_id
        }
        logger.info(f"Client {client_id} connected. Role: {role}, Event: {event_id}, Zone: {zone_id}")

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

    async def broadcast_authority(self, event_type: str, payload: dict, event_id: int):
        """Broadcast an event to all active Authority dashboards for a specific event."""
        message = self._build_envelope(event_type, payload)
        tasks = []
        for client_id, data in self.active_connections.items():
            if data["role"] == "AUTHORITY" and data["event_id"] == event_id:
                tasks.append(self._send_to_client(client_id, message))
        if tasks:
            await asyncio.gather(*tasks)

    async def broadcast_citizen_zone(self, zone_id: int, event_type: str, payload: dict, event_id: int):
        """Broadcast an event ONLY to Citizens currently located in the targeted zone_id within the event."""
        message = self._build_envelope(event_type, payload)
        tasks = []
        for client_id, data in self.active_connections.items():
            if data["role"] == "CITIZEN" and data["event_id"] == event_id and data["zone_id"] == zone_id:
                tasks.append(self._send_to_client(client_id, message))
        if tasks:
            await asyncio.gather(*tasks)

# Global manager instance
manager = ConnectionManager()
