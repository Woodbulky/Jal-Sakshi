"""Detection: sensor health, baselines, anomalies, fault classification.

Strictly downstream of telemetry. Nothing in this package may import from
`app.simulation` or read `fault_injections` — the classifier has to earn its
answer from the same readings a field deployment would have.
"""
