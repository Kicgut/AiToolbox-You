import asyncio

from app.ai_workbench.runtime_stream import RuntimeBroadcaster


def test_runtime_broadcast_delivers_without_blocking_and_unsubscribes():
    async def scenario():
        broadcaster = RuntimeBroadcaster()
        queue = await broadcaster.subscribe("r")
        broadcaster.publish({"run_id": "r", "sequence_no": 1, "event_type": "message.delta"})
        assert (await queue.get())["sequence_no"] == 1
        broadcaster.publish({"run_id": "other", "sequence_no": 1})
        assert queue.empty()
        broadcaster.unsubscribe("r", queue)
        broadcaster.publish({"run_id": "r", "sequence_no": 2})
        assert queue.empty()
    asyncio.run(scenario())
