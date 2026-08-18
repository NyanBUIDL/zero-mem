from zero_mem import CoreConfig, PublicClient


class Writer:
    def __init__(self):
        self.events = []
    def append(self, event):
        self.events.append(event)


def test_generic_fixture_uses_only_public_zero_mem_imports() -> None:
    writer = Writer()
    with PublicClient.open(CoreConfig(), writer=writer, consistency_policy="append") as client:
        client.session_start("generic-session")
        assert client.observe_message({"text": "generic"}).status == "CAPTURED"
        assert client.health().status == "OK"
    assert len(writer.events) == 1
