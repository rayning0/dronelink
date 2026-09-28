const joinButton = document.querySelector("#join");
const leaveButton = document.querySelector("#leave");
const armButton = document.querySelector("#arm");
const takeoffButton = document.querySelector("#takeoff");
const landButton = document.querySelector("#land");
const returnHomeButton = document.querySelector("#return-home");

const statusElement = document.querySelector("#status");
const remoteVideo = document.querySelector("#remote-video");
const telemetryElement = document.querySelector("#telemetry");
const acknowledgementElement = document.querySelector("#acknowledgement");
const failsafeElement = document.querySelector("#failsafe");

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();

const droneAgentIdentity = "drone-agent-01";
const movementKeys = new Set(["w", "a", "s", "d", "r", "f"]);

let room;
let movementTimer;
const pressedKeys = new Set();

joinButton.addEventListener("click", joinOperator);
leaveButton.addEventListener("click", leaveOperator);

armButton.addEventListener("click", () => sendReliableCommand("arm"));
takeoffButton.addEventListener("click", () => sendReliableCommand("takeoff"));
landButton.addEventListener("click", () => sendReliableCommand("land"));
returnHomeButton.addEventListener("click", () => sendReliableCommand("return_home"));

window.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();

    if (!room || !movementKeys.has(key)) {
        return;
    }

    event.preventDefault();

    const wasAlreadyPressed = pressedKeys.has(key);
    pressedKeys.add(key);

    if (!wasAlreadyPressed) {
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

        room.on(LivekitClient.RoomEvent.Disconnected, () => {
            stopMovementLoop();
            pressedKeys.clear();
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
    await publishCommand(
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
        return;
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
    } catch (error) {
        console.error("Could not publish command:", error);
        setStatus(statusElement, `Command failed: ${error.message}`, true);
    }
}

function startMovementLoop() {
    stopMovementLoop();

    // 8 Hz: fresh velocity commands replace old ones quickly.
    movementTimer = window.setInterval(() => {
        if (pressedKeys.size > 0) {
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

function leaveOperator() {
    stopMovementLoop();
    pressedKeys.clear();

    room?.disconnect();
    room = undefined;

    remoteVideo.innerHTML = "<p>Waiting for drone camera...</p>";
    setControlsEnabled(false);
    leaveButton.disabled = true;
    joinButton.disabled = false;
    failsafeElement.hidden = true;
    failsafeElement.textContent = "";
}
