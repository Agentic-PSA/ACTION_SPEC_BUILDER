import aio_pika
import json
from starlette.responses import JSONResponse
import os


# exchanges
# gen_descr.request.exchange - topic, durable
# gen_descr.response.exchange - topic, durable

# queues
# gen_descr.request.minimal.queue - quorum
# gen_descr.request.simple.queue - quorum
# gen_descr.response.created.queue - quorum
# gen_descr.response.failed.queue - quorum

# routings


# RabbitMQ config
EXCHANGE_NAME = "gen_descr.request.exchange"
RABBIT_USER=os.environ.get("RABBIT_USER")
RABBIT_PASS=os.environ.get("RABBIT_PASS")
RABBIT_HOST=os.environ.get("RABBIT_HOST")
RABBIT_PORT=os.environ.get("RABBIT_PORT")
RABBITMQ_URL = f"amqp://{RABBIT_USER}:{RABBIT_PASS}@{RABBIT_HOST}:{RABBIT_PORT}/"  # zmień jeśli trzeba

# Globalne połączenie / kanał
rabbit_connection = None
rabbit_channel = None

async def get_rabbit_channel():
    """
    Zwraca kanał RabbitMQ, tworzy jeśli jeszcze nie istnieje.
    """
    global rabbit_connection, rabbit_channel
    if rabbit_connection is None or rabbit_connection.is_closed:
        rabbit_connection = await aio_pika.connect_robust(RABBITMQ_URL)
        rabbit_channel = await rabbit_connection.channel()
        await rabbit_channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
    return rabbit_channel


async def create_description(request):
    """
    Endpoint API: przyjmuje JSON z type=minimal/simple/full
    i payload, publikuje wiadomość do RabbitMQ.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            content={"status": "error", "message": "Invalid JSON"},
            status_code=400
        )

    desc_type = data.get("type")
    if desc_type not in ["minimal", "simple", "full"]:
        return JSONResponse(
            content={"status": "error", "message": "Invalid type, must be 'minimal', 'simple' or 'full'"},
            status_code=400
        )

    routing_key = f"gen_descr.request.{desc_type}"

    message = {
        "request_id": data.get("request_id"),
        "payload": data.get("payload", {}),
        "type": desc_type
    }

    # Publikacja do RabbitMQ
    channel = await get_rabbit_channel()
    exchange = await channel.get_exchange(EXCHANGE_NAME)
    await exchange.publish(
        aio_pika.Message(
            body=json.dumps(message).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        ),
        routing_key=routing_key
    )
    return JSONResponse(
        {"status": "queued", "routing_key": routing_key}
    )

