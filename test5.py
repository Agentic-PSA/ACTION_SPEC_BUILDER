from azure.servicebus import ServiceBusClient, ServiceBusReceiveMode

CONNECTION_STR = "Endpoint=sb://sbactuat.servicebus.windows.net/;SharedAccessKeyName=SBActUatPolicy;SharedAccessKey=+yu3D3dQt8fsgI9TSzcC8uxDZpbCRFAmv+ASbBLK2n0="
TOPIC_NAME = "product"
SUBSCRIPTION_NAME = "BazaGrafowa"

with ServiceBusClient.from_connection_string(CONNECTION_STR) as client:
    session_id = "0"

    with client.get_subscription_receiver(
        topic_name=TOPIC_NAME,
        subscription_name=SUBSCRIPTION_NAME,
        session_id=session_id,
        receive_mode=ServiceBusReceiveMode.PEEK_LOCK
    ) as receiver:
        messages = receiver.peek_messages(max_message_count=5)
        for msg in messages:
            print("Body:", str(msg))
