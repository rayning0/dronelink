const joinButton = document.querySelector("#join");
const leaveButton = document.querySelector("#leave");
const statusElement = document.querySelector("#status");
const remoteVideo = document.querySelector("#remote-video");

let room;

joinButton.addEventListener("click", joinOperator);
leaveButton.addEventListener("click", leaveOperator);

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
                setStatus(
                    statusElement,
                    `Viewing camera from ${participant.identity}`,
                );
            },
        );

        room.on(LivekitClient.RoomEvent.Disconnected, () => {
            setStatus(statusElement, "Disconnected");
            remoteVideo.innerHTML = "<p>Waiting for drone camera...</p>";
            leaveButton.disabled = true;
            joinButton.disabled = false;
        });

        setStatus(statusElement, "Connecting to LiveKit...");
        await room.connect(LIVEKIT_URL, token);

        setStatus(statusElement, `Connected as ${identity}; waiting for camera...`);
        leaveButton.disabled = false;
    } catch (error) {
        console.error(error);
        setStatus(statusElement, `Could not join room: ${error.message}`, true);
        leaveOperator();
    }
}

function leaveOperator() {
    room?.disconnect();
    room = undefined;

    remoteVideo.innerHTML = "<p>Waiting for drone camera...</p>";
    leaveButton.disabled = true;
    joinButton.disabled = false;
}
