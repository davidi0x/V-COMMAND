class AuditLog:
    def __init__(self):
        self.entries = []

    def attach(self, bus):
        bus.subscribe("order.*", lambda topic, payload: self.entries.append((topic, payload)), with_topic=True)
