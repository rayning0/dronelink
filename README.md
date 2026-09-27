# DroneLink: A low-latency RemoteOps simulator
by Raymond Gan

A local [LiveKit](https://github.com/livekit/livekit)-based RemoteOps simulator demonstrating low-latency video, command validation, telemetry, and a dead-man failsafe.
```
Operator browser

↓  WebRTC video + data through LiveKit SFU

Golang RemoteOps gateway

 ↓

DroneAdapter interface

 ↓

SimulatedDrone implementation
```
Demo:
- A “drone camera” browser publishes its webcam video.
- An operator browser receives the live video.
- The operator sends flight commands.
- A Golang drone agent validates commands and returns telemetry.
- The demo visibly triggers a fail-safe if commands stop.
- Uses [LiveKit for the SFU](https://docs.livekit.io/reference/internals/livekit-sfu/).
- Uses Golang for token/control service and simulated drone agent.

This prototype uses a simulated drone adapter. A future MAVLinkAdapter could translate validated RemoteOps commands and telemetry to/from a flight controller or companion computer.
