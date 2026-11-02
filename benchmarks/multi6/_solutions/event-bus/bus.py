class EventBus:
    def __init__(self):
        self._subs = []  # (topic, handler, priority, seq, with_topic)
        self._seq = 0

    def subscribe(self, topic, handler, priority=0, with_topic=False):
        self._seq += 1
        self._subs.append((topic, handler, priority, self._seq, with_topic))

    def unsubscribe(self, topic, handler):
        self._subs = [s for s in self._subs if not (s[0] == topic and s[1] == handler)]

    @staticmethod
    def _matches(pattern, topic):
        if pattern.endswith(".*"):
            return topic.startswith(pattern[:-1])
        return pattern == topic

    def publish(self, topic, payload=None):
        matching = [s for s in self._subs if self._matches(s[0], topic)]
        matching.sort(key=lambda s: (-s[2], s[3]))
        errors = []
        for _, handler, _, _, with_topic in matching:
            try:
                handler(topic, payload) if with_topic else handler(payload)
            except Exception as error:  # noqa: BLE001 - isolation is the point
                errors.append(error)
        return errors
