const joinButton = document.querySelector("#join");
const leaveButton = document.querySelector("#leave");
const statusElement = document.querySelector("#status");
const preview = document.querySelector("#preview");

let room;
let cameraStream;

joinButton.addEventListener("click", joinDrone);
leaveButton.addEventListener("click", leaveDrone);

async function joinDrone() {
    joinButton.disabled = true;

    try {
        setStatus(statusElement, "Requesting camera permission...");

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 1280 },
                height: { ideal: 720 },
                frameRate: { ideal: 30 },
            },
            audio: false,
        });

        preview.srcObject = cameraStream;

        const { token, identity } = await requestToken(
            "drone-camera",
            "drone-camera",
        );

        room = new LivekitClient.Room({
            adaptiveStream: true,
            dynacast: true,
        });

        room.on(LivekitClient.RoomEvent.Disconnected, () => {
            setStatus(statusElement, "Disconnected");
            leaveButton.disabled = true;
            joinButton.disabled = false;
        });

        setStatus(statusElement, "Connecting to LiveKit...");
        await room.connect(LIVEKIT_URL, token);

        const cameraTrack = cameraStream.getVideoTracks()[0];

        await room.localParticipant.publishTrack(cameraTrack, {
            name: "drone-camera",
            source: LivekitClient.Track.Source.Camera,
        });

        setStatus(statusElement, `Publishing as ${identity}`);
        leaveButton.disabled = false;
    } catch (error) {
        console.error(error);
        setStatus(statusElement, `Could not publish camera: ${error.message}`, true);
        leaveDrone();
    }
}

function leaveDrone() {
    cameraStream?.getTracks().forEach((track) => track.stop());
    cameraStream = undefined;

    room?.disconnect();
    room = undefined;

    preview.srcObject = null;
    leaveButton.disabled = true;
    joinButton.disabled = false;
}
