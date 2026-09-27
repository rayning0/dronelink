const LIVEKIT_URL = "ws://127.0.0.1:7880";
const ROOM_NAME = "demo";

async function requestToken(role, identityPrefix) {
    const identity = `${identityPrefix}-${crypto.randomUUID().slice(0, 8)}`;

    const response = await fetch("/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            room: ROOM_NAME,
            identity,
            role,
        }),
    });

    if (!response.ok) {
        throw new Error(await response.text());
    }

    const { token } = await response.json();
    return { token, identity };
}

function setStatus(element, message, isError = false) {
    element.textContent = message;
    element.className = isError ? "error" : "";
}
