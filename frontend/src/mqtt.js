import mqtt from "mqtt";

const MQTT_URL = "ws://localhost:8083/mqtt";

export function createMqttClient() {
  const client = mqtt.connect(MQTT_URL, {
    username: "admin",
    password: "public",
    clean: true,
    reconnectPeriod: 1000,
  });

  client.on("connect", () => {
    console.log("MQTT connected");
  });

  client.on("error", (err) => {
    console.error("MQTT error", err);
  });

  return client;
}

export function subscribeToChatStream({
  client,
  streamTopic,
  doneTopic,
  onToken,
  onDone,
  onError,
}) {
  const topics = [streamTopic, doneTopic];

  client.subscribe(topics, { qos: 1 }, (err) => {
    if (err) {
      onError?.(err);
    } else {
      console.log("Subscribed topics:", topics);
    }
  });

  const handleMessage = (topic, payloadBuffer) => {
    try {
      const raw = payloadBuffer.toString();
      console.log("MQTT topic:", topic);
      console.log("MQTT raw payload:", raw);

      const payload = JSON.parse(raw);

      if (topic === streamTopic) {
        const piece =
          payload.token ??
          payload.content ??
          payload.text ??
          payload.delta ??
          "";

        if (piece) {
          onToken?.(piece);
        }
      }

      if (topic === doneTopic) {
        if (payload.error) {
          onError?.(new Error(payload.error));
        } else {
          onDone?.(payload);
        }
      }
    } catch (err) {
      onError?.(err);
    }
  };

  client.on("message", handleMessage);

  return () => {
    client.off("message", handleMessage);
    client.unsubscribe(topics);
  };
}
