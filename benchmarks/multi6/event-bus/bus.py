class EventBus:
    def subscribe(self, topic, handler, priority=0):
        raise NotImplementedError

    def unsubscribe(self, topic, handler):
        raise NotImplementedError

    def publish(self, topic, payload=None):
        raise NotImplementedError
