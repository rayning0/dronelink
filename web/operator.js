const joinButton = document.querySelector("#join");
const leaveButton = document.querySelector("#leave");
const armButton = document.querySelector("#arm");
const takeoffButton = document.querySelector("#takeoff");
const landButton = document.querySelector("#land");
const returnHomeButton = document.querySelector("#return-home");
const flightStateElement = document.querySelector("#flight-state");

const statusElement = document.querySelector("#status");
const remoteVideo = document.querySelector("#remote-video");
const telemetryElement = document.querySelector("#telemetry");
const acknowledgementElement = document.querySelector("#acknowledgement");
const failsafeElement = document.querySelector("#failsafe");
const linkHealthElement = document.querySelector("#link-health");
const flightStageElement = document.querySelector("#flight-stage");
const lateralDroneElement = document.querySelector("#lateral-drone");
const altitudeDroneElement = document.querySelector("#altitude-drone");

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();

const droneAgentIdentity = "drone-agent-01";
const movementKeys = new Set(["w", "a", "s", "d", "r", "f"]);

let room;
let movementTimer;
let remoteVideoTrack;
let statsTimer;
let previousInboundVideoStats;
let connectionState = "not connected";
const pressedKeys = new Set();
const lateralPosition = { x: 0, y: 0 };
let altitudePosition = 0;
let isFlightSequenceRunning = false;
const flightVisualizationEdgePadding = 8;

function updateFlightState(state) {
    for (const stateElement of flightStateElement.querySelectorAll("[data-state]")) {
        stateElement.classList.toggle("current", stateElement.dataset.state === state);
    }
}

joinButton.addEventListener("click", joinOperator);
leaveButton.addEventListener("click", leaveOperator);

armButton.addEventListener("click", () => sendReliableCommand("arm"));
takeoffButton.addEventListener("click", () => sendReliableCommand("takeoff"));
landButton.addEventListener("click", () => sendReliableCommand("land"));
returnHomeButton.addEventListener("click", () => void returnHomeAndLand());

window.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();

    if (!room || !movementKeys.has(key)) {
        return;
    }

    event.preventDefault();

    if (isFlightSequenceRunning) {
        return;
    }

    const wasAlreadyPressed = pressedKeys.has(key);
    pressedKeys.add(key);

    if (!wasAlreadyPressed) {
        updateFlightVisualization();
        void sendVelocity();
    }
});

window.addEventListener("keyup", (event) => {
    const key = event.key.toLowerCase();

    if (!movementKeys.has(key)) {
        return;
    }

    event.preventDefault();
    pressedKeys.delete(key);

    // Send an immediate stop/update when a key is released.
    void sendVelocity();
    updateFlightVisualization();
});

async function joinOperator() {
    joinButton.disabled = true;

    try {
        const { token, identity } = await requestToken("operator", "operator");

        room = new LivekitClient.Room({
            adaptiveStream: true,
            dynacast: true,
        });

        room.on(
            LivekitClient.RoomEvent.TrackSubscribed,
            (track, publication, participant) => {
                if (
                    track.kind !== LivekitClient.Track.Kind.Video ||
                    publication.source !== LivekitClient.Track.Source.Camera
                ) {
                    return;
                }

                const video = track.attach();
                video.autoplay = true;
                video.playsInline = true;

                remoteVideo.replaceChildren(video);

                // Save the actual received WebRTC video track for the stats panel.
                remoteVideoTrack = track;
                startStatsLoop();

                setStatus(statusElement, `Viewing camera from ${participant.identity}`);
            },
        );

        room.on(
            LivekitClient.RoomEvent.DataReceived,
            (payload, participant) => {
                if (participant?.identity !== droneAgentIdentity) {
                    return;
                }

                let message;

                try {
                    message = JSON.parse(textDecoder.decode(payload));
                } catch (error) {
                    console.error("Could not parse drone-agent data:", error);
                    return;
                }

                if (message.type === "telemetry") {
                    updateFlightState(message.state);
                    telemetryElement.textContent = [
                        `State: ${message.state}`,
                        `Battery: ${message.batteryPct.toFixed(2)}%`,
                        `Altitude: ${message.altitudeM.toFixed(1)} m`,
                        `Velocity: forward=${message.velocity.forward}, right=${message.velocity.right}, up=${message.velocity.up}`,
                        `Failsafe: ${message.failsafeReason || "none"}`,
                        `Last accepted command: ${message.lastCommandAt ?? "none"}`,
                        `Updated: ${new Date(message.sentAt).toLocaleTimeString()}`,
                    ].join("\n");

                    if (message.state === "HOVER_FAILSAFE") {
                        failsafeElement.textContent = `FAILSAFE ACTIVE: ${message.failsafeReason}`;
                        failsafeElement.hidden = false;
                    } else {
                        failsafeElement.hidden = true;
                        failsafeElement.textContent = "";
                    }
                }

                if (message.type === "ack") {
                    updateFlightState(message.state);
                    acknowledgementElement.textContent = [
                        `Command: ${message.action}`,
                        `Command ID: ${message.commandId}`,
                        `Accepted: ${message.accepted}`,
                        `State: ${message.state}`,
                        `Reason: ${message.reason || "none"}`,
                    ].join("\n");
                }
            },
        );

        room.on(LivekitClient.RoomEvent.ConnectionStateChanged, (state) => {
            connectionState = String(state);
            void updateLinkHealth();
        });

        room.on(LivekitClient.RoomEvent.Disconnected, () => {
            stopMovementLoop();
            pressedKeys.clear();
            resetFlightVisualization();
            setStatus(statusElement, "Disconnected");
            remoteVideo.innerHTML = "<p>Waiting for drone camera...</p>";
            setControlsEnabled(false);
            leaveButton.disabled = true;
            joinButton.disabled = false;
            failsafeElement.hidden = true;
            failsafeElement.textContent = "";
        });

        setStatus(statusElement, "Connecting to LiveKit...");
        await room.connect(LIVEKIT_URL, token);
        connectionState = "connected";

        startMovementLoop();

        setStatus(statusElement, `Connected as ${identity}; waiting for camera...`);
        setControlsEnabled(true);
        leaveButton.disabled = false;
    } catch (error) {
        console.error(error);
        setStatus(statusElement, `Could not join room: ${error.message}`, true);
        leaveOperator();
    }
}

function setControlsEnabled(enabled) {
    armButton.disabled = !enabled;
    takeoffButton.disabled = !enabled;
    landButton.disabled = !enabled;
    returnHomeButton.disabled = !enabled;
}

async function sendReliableCommand(action) {
    return publishCommand(
        {
            type: "command",
            id: crypto.randomUUID(),
            action,
            sentAt: new Date().toISOString(),
            velocity: { forward: 0, right: 0, up: 0 },
        },
        true,
    );
}

async function sendVelocity() {
    if (!room || pressedKeys.size === 0) {
        await publishCommand(
            {
                type: "command",
                id: crypto.randomUUID(),
                action: "set_velocity",
                sentAt: new Date().toISOString(),
                velocity: { forward: 0, right: 0, up: 0 },
            },
            false,
        );
        return;
    }

    const velocity = {
        forward: Number(pressedKeys.has("w")) - Number(pressedKeys.has("s")),
        right: Number(pressedKeys.has("d")) - Number(pressedKeys.has("a")),
        up: Number(pressedKeys.has("r")) - Number(pressedKeys.has("f")),
    };

    await publishCommand(
        {
            type: "command",
            id: crypto.randomUUID(),
            action: "set_velocity",
            sentAt: new Date().toISOString(),
            velocity,
        },
        false,
    );
}

async function publishCommand(command, reliable) {
    if (!room) {
        return false;
    }

    try {
        await room.localParticipant.publishData(
            textEncoder.encode(JSON.stringify(command)),
            {
                reliable,
                destinationIdentities: [droneAgentIdentity],
                topic: "remoteops.command",
            },
        );

        setStatus(
            statusElement,
            reliable
                ? `Sent reliable ${command.action} command`
                : "Sending live velocity commands",
        );
        return true;
    } catch (error) {
        console.error("Could not publish command:", error);
        setStatus(statusElement, `Command failed: ${error.message}`, true);
        return false;
    }
}

async function returnHomeAndLand() {
    if (!room || isFlightSequenceRunning) {
        return;
    }

    isFlightSequenceRunning = true;
    returnHomeButton.disabled = true;
    pressedKeys.clear();
    void sendVelocity();
    flightStageElement.classList.add("is-moving");

    const returnHomeSent = await sendReliableCommand("return_home");
    if (!returnHomeSent) {
        finishReturnHomeSequence();
        return;
    }

    setStatus(statusElement, "Returning home: moving to the home position...");
    await animateLateralDroneToCenter();

    // This is a separate, real reliable command. It is deliberately not sent
    // until the return-home visualization has reached the center.
    const landSent = await sendReliableCommand("land");
    if (!landSent) {
        finishReturnHomeSequence();
        return;
    }

    setStatus(statusElement, "Landing at home...");
    await animateAltitudeDroneToBottom();
    setStatus(statusElement, "Landed at home. Holding the completed flight view...");
    await wait(5000);
    finishReturnHomeSequence();
}

function finishReturnHomeSequence() {
    isFlightSequenceRunning = false;
    resetFlightVisualization();
    if (room) {
        returnHomeButton.disabled = false;
    }
}

function startMovementLoop() {
    stopMovementLoop();

    // 8 Hz: fresh velocity commands replace old ones quickly.
    movementTimer = window.setInterval(() => {
        if (pressedKeys.size > 0) {
            updateFlightVisualization();
            void sendVelocity();
        }
    }, 125);
}

function stopMovementLoop() {
    if (movementTimer) {
        window.clearInterval(movementTimer);
        movementTimer = undefined;
    }
}

function updateFlightVisualization() {
    const isMoving = pressedKeys.size > 0 || isFlightSequenceRunning;
    flightStageElement.classList.toggle("is-moving", isMoving);

    if (!isMoving) {
        return;
    }

    const lateralStep = 7;
    const altitudeStep = 7;

    // W is forward/up on the top-down map; S is backward/down.
    lateralPosition.y += lateralStep * (
        Number(pressedKeys.has("s")) - Number(pressedKeys.has("w"))
    );
    lateralPosition.x += lateralStep * (
        Number(pressedKeys.has("d")) - Number(pressedKeys.has("a"))
    );

    // R ascends on the side view; F descends.
    altitudePosition += altitudeStep * (
        Number(pressedKeys.has("f")) - Number(pressedKeys.has("r"))
    );

    const lateralXLimit = movementLimit(lateralDroneElement, "width");
    const lateralYLimit = movementLimit(lateralDroneElement, "height");
    const altitudeYLimit = movementLimit(altitudeDroneElement, "height");

    lateralPosition.x = clamp(lateralPosition.x, -lateralXLimit, lateralXLimit);
    lateralPosition.y = clamp(lateralPosition.y, -lateralYLimit, lateralYLimit);
    altitudePosition = clamp(altitudePosition, -altitudeYLimit, altitudeYLimit);

    renderFlightVisualization();
}

function renderFlightVisualization() {
    lateralDroneElement.style.transform =
        `translate(calc(-50% + ${lateralPosition.x}px), calc(-50% + ${lateralPosition.y}px))`;
    altitudeDroneElement.style.transform =
        `translate(-50%, calc(-50% + ${altitudePosition}px))`;
}

async function animateLateralDroneToCenter() {
    const startingX = lateralPosition.x;
    const startingY = lateralPosition.y;

    await animateOver(5000, (progress) => {
        lateralPosition.x = startingX * (1 - progress);
        lateralPosition.y = startingY * (1 - progress);
        renderFlightVisualization();
    });
}

async function animateAltitudeDroneToBottom() {
    const startingY = altitudePosition;
    const lane = altitudeDroneElement.parentElement;
    const bottomY = Math.max(
        0,
        lane.clientHeight / 2 - altitudeDroneElement.clientHeight / 2 - flightVisualizationEdgePadding,
    );

    await animateOver(5000, (progress) => {
        altitudePosition = startingY + (bottomY - startingY) * progress;
        renderFlightVisualization();
    });
}

function animateOver(durationMs, onProgress) {
    return new Promise((resolve) => {
        const startedAt = performance.now();

        function frame(now) {
            const progress = Math.min(1, (now - startedAt) / durationMs);
            onProgress(progress);

            if (progress < 1) {
                requestAnimationFrame(frame);
            } else {
                resolve();
            }
        }

        requestAnimationFrame(frame);
    });
}

function wait(durationMs) {
    return new Promise((resolve) => window.setTimeout(resolve, durationMs));
}

function resetFlightVisualization() {
    isFlightSequenceRunning = false;
    lateralPosition.x = 0;
    lateralPosition.y = 0;
    altitudePosition = 0;
    flightStageElement.classList.remove("is-moving");
    lateralDroneElement.style.transform = "translate(-50%, -50%)";
    altitudeDroneElement.style.transform = "translate(-50%, -50%)";
}

function clamp(value, minimum, maximum) {
    return Math.min(Math.max(value, minimum), maximum);
}

function movementLimit(marker, dimension) {
    const container = marker.parentElement;
    const containerSize = dimension === "width" ? container.clientWidth : container.clientHeight;
    const markerSize = dimension === "width" ? marker.clientWidth : marker.clientHeight;

    return Math.max(0, containerSize / 2 - markerSize / 2 - flightVisualizationEdgePadding);
}

function leaveOperator() {
    stopMovementLoop();
    pressedKeys.clear();
    resetFlightVisualization();

    room?.disconnect();
    room = undefined;

    remoteVideo.innerHTML = "<p>Waiting for drone camera...</p>";
    setControlsEnabled(false);
    leaveButton.disabled = true;
    joinButton.disabled = false;
    failsafeElement.hidden = true;
    failsafeElement.textContent = "";
    stopStatsLoop();
    connectionState = "not connected";
}

// *******************************************************************
// Add WebRTC stats:

// connection state (connecting, connected, disconnected, or failed)
// selected candidate pair:
//    - host: A direct local connection (in same network).
//    - srflx (Server Reflexive): A direct connection across the internet, resolved via a STUN server.
//    - relay: Traffic bounced through a TURN server because a strict firewall blocked direct connection.
// RTT(Round-Trip Time) in ms: tells network latency. Low RTT (< 50–100ms) means a highly responsive, real-time connection. High RTT causes noticeable delays in conversation.
// packet loss: % or count of data packets sent but never arrived at destination.
// jitter (ms): fluctuation in arrival time of data packets. If Packet A takes 20ms and Packet B takes 80ms, the jitter is high. High jitter makes audio sound choppy or robotic and makes video stutter.
// inbound video bitrate (kbps): actual bandwidth consumption and quality of incoming video stream.

function startStatsLoop() {
    stopStatsLoop(false);

    void updateLinkHealth();
    statsTimer = window.setInterval(() => {
        void updateLinkHealth();
    }, 1000);
}

function stopStatsLoop(clearTrack = true) {
    if (statsTimer) {
        window.clearInterval(statsTimer);
        statsTimer = undefined;
    }

    previousInboundVideoStats = undefined;

    if (clearTrack) {
        remoteVideoTrack = undefined;
    }

    linkHealthElement.textContent = "Waiting for video statistics...";
}

async function updateLinkHealth() {
    if (!remoteVideoTrack) {
        linkHealthElement.textContent =
            `Connection state: ${connectionState}\nVideo stats: waiting for drone camera track`;
        return;
    }

    try {
        const report = await remoteVideoTrack.getRTCStatsReport();

        if (!report) {
            linkHealthElement.textContent =
                `Connection state: ${connectionState}\nVideo stats: unavailable in this browser`;
            return;
        }

        let inboundVideo;
        let remoteOutboundVideo;
        let selectedCandidatePair;

        report.forEach((stat) => {
            const isVideo = stat.kind === "video" || stat.mediaType === "video";

            if (stat.type === "inbound-rtp" && isVideo) {
                inboundVideo = stat;
            }

            if (stat.type === "remote-outbound-rtp" && isVideo) {
                remoteOutboundVideo = stat;
            }

            if (
                stat.type === "candidate-pair" &&
                stat.state === "succeeded" &&
                (stat.nominated || stat.selected)
            ) {
                selectedCandidatePair = stat;
            }
        });

        if (!inboundVideo) {
            linkHealthElement.textContent =
                `Connection state: ${connectionState}\nInbound video stats: not available yet`;
            return;
        }

        const now = performance.now();
        let bitrateText = "calculating...";

        if (previousInboundVideoStats) {
            const elapsedSeconds =
                (now - previousInboundVideoStats.observedAt) / 1000;
            const byteDelta =
                inboundVideo.bytesReceived - previousInboundVideoStats.bytesReceived;

            if (elapsedSeconds > 0) {
                const kbps = Math.max(0, (byteDelta * 8) / elapsedSeconds / 1000);
                bitrateText = `${kbps.toFixed(0)} kbps`;
            }
        }

        previousInboundVideoStats = {
            bytesReceived: inboundVideo.bytesReceived ?? 0,
            observedAt: now,
        };

        const localCandidate = selectedCandidatePair
            ? report.get(selectedCandidatePair.localCandidateId)
            : undefined;
        const remoteCandidate = selectedCandidatePair
            ? report.get(selectedCandidatePair.remoteCandidateId)
            : undefined;

        const candidateTypes =
            localCandidate?.candidateType && remoteCandidate?.candidateType
                ? `${localCandidate.candidateType} → ${remoteCandidate.candidateType}`
                : "unavailable";

        const rttSeconds =
            selectedCandidatePair?.currentRoundTripTime ??
            remoteOutboundVideo?.roundTripTime;

        const rttText =
            typeof rttSeconds === "number"
                ? `${(rttSeconds * 1000).toFixed(1)} ms`
                : "unavailable";

        const jitterText =
            typeof inboundVideo.jitter === "number"
                ? `${(inboundVideo.jitter * 1000).toFixed(1)} ms`
                : "unavailable";

        const packetsReceived = inboundVideo.packetsReceived ?? 0;
        const packetsLost = inboundVideo.packetsLost ?? 0;
        const totalPackets = packetsReceived + packetsLost;
        const lossPercent =
            totalPackets > 0 ? (packetsLost / totalPackets) * 100 : 0;

        linkHealthElement.textContent = [
            `Connection state: ${connectionState}`,
            `Candidate pair: ${candidateTypes}`,
            `RTT (Round-Trip Time): ${rttText}`,
            `Packet loss: ${lossPercent.toFixed(2)}% (${packetsLost} lost)`,
            `Jitter: ${jitterText}`,
            `Inbound video bitrate: ${bitrateText}`,
        ].join("\n");
    } catch (error) {
        linkHealthElement.textContent =
            `Connection state: ${connectionState}\nUnable to read RTC statistics: ${error.message}`;
    }
}
