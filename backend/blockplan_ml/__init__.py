"""Learned duration estimation, kept entirely outside the frozen planning path.

Nothing here is imported by blockplan_service or blockplan_api unless
BLOCKPLAN_DURATION_SOURCE asks for it, and it is `catalogue` -- today's
behaviour -- by default. core.py is not touched.
"""
