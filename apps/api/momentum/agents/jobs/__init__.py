"""Phase 7.6 S76-02 (spec §4): durable jobs. A pack's work runs as a job: an ordinary async function
replayed from the top on every claim, whose steps run once and are recorded (``job.py``), driven
by the engine (``engine.py``) and controlled by people (``control.py``)."""
