"""M9: Offline Edge Gateway package.

A small site-local runtime with a durable SQLite store. It degrades gracefully
when the Central VPS is unreachable and synchronizes later with at-least-once
delivery + application-level idempotency.
"""
