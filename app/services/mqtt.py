from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiomqtt

from app.core.config import settings

logger = logging.getLogger(__name__)

MQTT_HOST = getattr(settings, "MQTT_HOST", "emqx")
MQTT_PORT = int(getattr(settings, "MQTT_PORT", 1883))
MQTT_USERNAME = getattr(settings, "MQTT_USERNAME", "admin")
MQTT_PASSWORD = getattr(settings, "MQTT_PASSWORD", "public")


def get_stream_topic(conversation_id: int, message_id: int) -> str:
    return f"ai/chat/{conversation_id}/{message_id}/stream"


def get_done_topic(conversation_id: int, message_id: int) -> str:
    return f"ai/chat/{conversation_id}/{message_id}/done"


@asynccontextmanager
async def get_mqtt_client() -> AsyncGenerator[aiomqtt.Client, None]:
    async with aiomqtt.Client(
        hostname=MQTT_HOST,
        port=MQTT_PORT,
        username=MQTT_USERNAME,
        password=MQTT_PASSWORD,
        timeout=10,
    ) as client:
        logger.debug("MQTT bağlantısı açıldı: %s:%d", MQTT_HOST, MQTT_PORT)
        try:
            yield client
        finally:
            logger.debug("MQTT bağlantısı kapatıldı")


async def publish_token(
    client: aiomqtt.Client,
    conversation_id: int,
    message_id: int,
    token: str,
) -> None:
    topic = get_stream_topic(conversation_id, message_id)
    payload = json.dumps({"token": token, "done": False})
    # retain=False — token'lar geçici, sadece anlık subscriber'lar alır
    await client.publish(topic, payload=payload, qos=1, retain=False)


async def publish_done(
    client: aiomqtt.Client,
    conversation_id: int,
    message_id: int,
    full_text: str,
    meta: dict,
) -> None:
    topic = get_done_topic(conversation_id, message_id)
    payload = json.dumps({
        "done": True,
        "full_text": full_text,
        "meta": meta,
    })
    # retain=True — frontend geç bağlansa bile done mesajını alır (race condition fix)
    await client.publish(topic, payload=payload, qos=1, retain=True)


async def publish_error(
    client: aiomqtt.Client,
    conversation_id: int,
    message_id: int,
    error: str,
) -> None:
    topic = get_done_topic(conversation_id, message_id)
    payload = json.dumps({
        "done": True,
        "error": error,
    })
    # retain=True — hata mesajı da geç gelen frontend'e ulaşsın
    await client.publish(topic, payload=payload, qos=1, retain=True)