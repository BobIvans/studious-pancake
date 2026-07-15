"""Pytest compatibility helpers."""

import asyncio


class CompatibilityEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    """Restore pre-3.14 get_event_loop behavior expected by legacy tests."""

    def get_event_loop(self):
        try:
            return super().get_event_loop()
        except RuntimeError:
            loop = self.new_event_loop()
            self.set_event_loop(loop)
            return loop


asyncio.set_event_loop_policy(CompatibilityEventLoopPolicy())
