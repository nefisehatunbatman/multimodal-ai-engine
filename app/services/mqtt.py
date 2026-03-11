from __future__ import annotations

import json
import logging

import aiomqtt

from app.core.config import settings

logger = logging.getLogger(__name__)

MQTT_HOST = getattr(settings, "MQTT_HOST", "emqx")
MQTT_PORT = int(getattr(settings, "MQTT_PORT", 1883))
MQTT_USERNAME = getattr(settings, "MQTT_USERNAME", "admin")
MQTT_PASSWORD = getattr(settings, "MQTT_PASSWORD", "public")


def get_stream_topic(conversation_id: int, message_id: int) -> str:
    # Token'ların publish edileceği topic
    return f"ai/chat/{conversation_id}/{message_id}/stream"


def get_done_topic(conversation_id: int, message_id: int) -> str:
    # Tamamlandı sinyalinin publish edileceği topic
    return f"ai/chat/{conversation_id}/{message_id}/done"


async def publish_token(
    client: aiomqtt.Client,
    conversation_id: int,
    message_id: int,
    token: str,
) -> None:
    # Tek bir token'ı MQTT topic'e publish et
    topic = get_stream_topic(conversation_id, message_id)
    payload = json.dumps({"token": token, "done": False})
    await client.publish(topic, payload=payload, qos=1)


async def publish_done(
    client: aiomqtt.Client,
    conversation_id: int,
    message_id: int,
    full_text: str,
    meta: dict,
) -> None:
    # Streaming tamamlandı sinyali gönder
    topic = get_done_topic(conversation_id, message_id)
    payload = json.dumps({
        "done": True,
        "full_text": full_text,
        "meta": meta,
    })
    await client.publish(topic, payload=payload, qos=1)


async def publish_error(
    client: aiomqtt.Client,
    conversation_id: int,
    message_id: int,
    error: str,
) -> None:
    # Hata durumunda MQTT'ye error mesajı gönder
    topic = get_done_topic(conversation_id, message_id)
    payload = json.dumps({
        "done": True,
        "error": error,
    })
    await client.publish(topic, payload=payload, qos=1)


async def get_mqtt_client() -> aiomqtt.Client:
    # MQTT client oluştur ve döndür
    return aiomqtt.Client(
        hostname=MQTT_HOST,
        port=MQTT_PORT,
        username=MQTT_USERNAME,
        password=MQTT_PASSWORD,
    )