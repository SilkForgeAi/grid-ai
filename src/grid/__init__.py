"""Grid AI — a self-correcting, teaching-first personal coding agent.

Grid AI is built *on top of* openhands-sdk (see ROADMAP §2). This package holds
only the parts the SDK does not provide: the Green/Yellow/Red autonomy gate, a
per-action confidence signal, a test-regression detector, tuned stuck-detection,
and the teaching layer. The SDK supplies the agent loop, event stream, tools,
sandbox, and model router.
"""

__version__ = "0.2.0"
