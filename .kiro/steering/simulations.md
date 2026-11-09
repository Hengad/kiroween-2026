---
inclusion: fileMatch
fileMatchPattern: '**/simulation/**'
---

# Simulations

Each demo app ships a simulation that plays the role of the real world, so the engine can be demonstrated end to end without real organizational systems.

- **siloless-factory**: a multi-stage manufacturing line.
- **siloless-festival**: a crowd simulation for a festival.

Detailed requirements for both will be supplied by the user. Until then, do not invent domain rules; ask, or leave a `TODO(user-input)` comment and note it in the response.

## Rules that apply to both

- **The simulation is a Source, not part of the engine.** It produces the kinds of data a real organization would have (sensor readings, operational events, messages, schedule changes, inventory movements) and delivers them through the app's Connectors via public ingestion interfaces. It never writes to the engine database and the engine never imports the simulation.
- **Deterministic and reproducible.** A run is fully determined by its scenario and seed. Use an injected clock that supports accelerated and stepped time, and a seeded random generator. Tests step the simulation explicitly; no real-time waits.
- **Scenario driven.** Scenarios are declarative data files (YAML or JSON) describing the initial state and scripted incidents (for example a sensor fault at t=120s, a supplier delay, a gate closure). Scripted incidents are how the demo shows Signals turning into incidents and Work Items.
- **Simulated workers talk.** The simulation includes the organization's people. They post questions, requests and announcements to the built-in communication channel, answer or claim tracked questions, and are the candidates for auto-assignment. Their messages enter the engine through the same connector as the user's messages.
- **Separate model from transport.** The step function (`state, inputs, rng → new state, emitted events`) is pure and unit tested. Publishing events to connectors and streaming state to the UI is a thin layer on top.
- **Observable.** The simulation exposes its own state stream for the visualization panel on the left side of the demo's split screen, separate from the data it feeds into the engine.
- **Controllable from the demo UI.** Start, pause, step, reset, change speed, and trigger scripted incidents on demand, so the demo video can be recorded reliably.
