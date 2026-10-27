# Keyframe Recovery Controller

# Problem: Video streaming relies on a Keyframe (I-frame/IDR) followed by a series of delta frames (P-frames) that only record changes. If a drone's wireless signal drops packets during an I-frame or a critical P-frame, the decoder on the operator's end cannot render the video properly.

# Visual Impact: Operator sees a frozen screen, heavy pixelation, or green artifacts. Since P-frames depend on the missing data, the video cannot recover on its own until the next scheduled keyframe.

# A remote drone video stream uses an inter-frame codec such as H.264 or H.265.

# Most video frames depend on earlier frames. If a receiver loses an important keyframe, or enough dependent packets, it may stop decoding usable video. The receiver should request a new keyframe, but must not flood the sender with requests.

# Build an in-memory controller that detects a decoder stall and manages keyframe requests.

# You are not implementing RTP, RTCP, H.264, or LiveKit. This is a state-management exercise that represents the policy around an RTCP PLI/keyframe request.

# https://bloggeek.me/webrtcglossary/pli/
# PLI = "Picture Loss Indication". It is one of the error resiliency mechanisms in WebRTC.
# A PLI can be sent when the receiver of the media lost a full frame or more. It is sent over RTCP. A receiver of this message can decide to resend a full frame (known as a keyframe) if he has one available in cache and finds it usable.

# “Treat a lack of decoded frames as a decoder health problem, not automatically a network problem. The controller sends a rate-limited keyframe request, then waits for a decoded keyframe before declaring recovery. In production, I would connect this policy to RTCP PLI/FIR feedback, track keyframe-request rate and recovery latency, and escalate to a stream restart or reconnect if repeated requests fail.”

# Drone encoder
# → RTP/WebRTC network
# → LiveKit SFU
# → Operator browser decoder

# If the browser stops decoding frames:

# Operator/browser
# → Sends RTCP PLI / keyframe request
# Instead of waiting seconds for the next scheduled keyframe, drone operator's decoder immediately sends a Picture Loss Indication (PLI) message back to the drone.
# Typically sent by RTCP (RTP Control Protocol) over the feedback channel. It tells drone encoder: "I have lost sync and cannot decode the current stream."

# → SFU forwards feedback upstream
# → drone encoder emits new H.264 IDR (Instantaneous Decoder Refresh) / H.265 keyframe
# An IDR frame is a special type of I-frame that acts as a hard reset. It tells the operator's decoder to empty its reference frame buffer and start fresh. As soon as this IDR frame arrives at the controller, the video instantly snaps back to a clear, crisp live image.

# → browser resumes decoding

# Your class decides when the conceptual REQUEST_KEYFRAME action should be sent.

class KeyframeRecoveryController:
    def __init__(
        self,

        # Max time a receiver can go without successfully decoding ANY video frame
        # (keyframe or not) before treating the video as stalled.
        # Normal video frames could arrive 30 times/s,
        # Keyframes may be much farther apart (every 1–2 seconds).
        frame_timeout_ms=1000,

        # Min delay between repeated keyframe requests while recovery has not succeeded.
        keyframe_request_cooldown_ms=500,
    ):
        """Create a controller with positive timeout and cooldown."""
        if frame_timeout_ms <= 0 or keyframe_request_cooldown_ms <= 0:
            raise ValueError('Both frame_timeout_ms and keyframe_request_cooldown_ms must be positive')

        self.state = "HEALTHY"
        self.frame_timeout_ms = frame_timeout_ms
        self.keyframe_request_cooldown_ms = keyframe_request_cooldown_ms

        self.last_decoded_frame_at_ms = None
        self.last_keyframe_request_at_ms = None
        self.keyframe_requests_sent = 0

    def on_stream_started(self, now_ms):
        """Starts observing a newly connected stream."""
        self.last_decoded_frame_at_ms = now_ms
        self.state = 'HEALTHY'
        self.last_keyframe_request_at_ms = None
        self.keyframe_requests_sent = 0

    def on_frame_decoded(self, now_ms, is_keyframe):
        """
        Record a successfully decoded frame.
        A decoded keyframe recovers the stream if waiting.
        """
        self.last_decoded_frame_at_ms = now_ms
        if is_keyframe and self.state == 'WAITING_FOR_KEYFRAME':
            self.state = 'HEALTHY'
            self.last_keyframe_request_at_ms = None

    def tick(self, now_ms):
        """
        Check for a stalled stream.

        Return {"type": "REQUEST_KEYFRAME", "reason": "..."}
        when a new keyframe request should be sent; otherwise None.
        """
        # stream hasn't started
        if self.last_decoded_frame_at_ms is None:
            return

        if self.state == 'HEALTHY':
            # request frame timeout (since last decoded frame) has not elapsed
            if now_ms - self.last_decoded_frame_at_ms < self.frame_timeout_ms:
                return
            else:
                # video has stalled
                self.state = 'WAITING_FOR_KEYFRAME'
                self.last_keyframe_request_at_ms = now_ms
                self.keyframe_requests_sent += 1
                return {
                    'type': 'REQUEST_KEYFRAME',
                    'reason': 'no decodable frame within timeout',
                }

        if self.state == 'WAITING_FOR_KEYFRAME':
            # request frame cooldown (since last keyframe request) has not elapsed
            if now_ms - self.last_keyframe_request_at_ms < self.keyframe_request_cooldown_ms:
                return
            else:
                self.last_keyframe_request_at_ms = now_ms
                self.keyframe_requests_sent += 1
                return {
                    'type': 'REQUEST_KEYFRAME',
                    'reason': 'no decodable frame within timeout',
                }


    def snapshot(self):
        """Return controller state for telemetry/debugging."""
        return {
            'state': self.state,
            'last_decoded_frame_at_ms': self.last_decoded_frame_at_ms,
            'last_keyframe_request_at_ms': self.last_keyframe_request_at_ms,
            'keyframe_requests_sent': self.keyframe_requests_sent,
        }

if __name__ == '__main__':
    try:
        c = KeyframeRecoveryController(0, -100)
    except ValueError as e:
        assert str(e) == 'Both frame_timeout_ms and keyframe_request_cooldown_ms must be positive'

    c = KeyframeRecoveryController()
    assert c.state == 'HEALTHY'

    # Normal decoded frames refresh the timeout
    c.on_stream_started(1000)
    c.on_frame_decoded(1500, is_keyframe=False)
    assert c.last_decoded_frame_at_ms == 1500
    assert c.state == 'HEALTHY'

    # The decoded frame at 1500 resets the timeout clock to 1500.
    assert c.tick(2499) is None     # 999 ms
    assert c.state == "HEALTHY"
    assert c.tick(2500)["type"] == "REQUEST_KEYFRAME"   # 1000 ms (new timeout)
    assert c.state == "WAITING_FOR_KEYFRAME"

    # At 999 ms (< 1000 ms timeout), it makes NO keyframe requests
    c = KeyframeRecoveryController(frame_timeout_ms=1000)
    c.on_stream_started(1000)
    assert c.tick(1999) is None
    assert c.state == 'HEALTHY'
    assert c.keyframe_requests_sent == 0

    # At timeout (1000 ms), it makes keyframe request
    assert c.tick(2000) == {
        'type': 'REQUEST_KEYFRAME',
        'reason': 'no decodable frame within timeout',
    }
    assert c.keyframe_requests_sent == 1
    assert c.last_keyframe_request_at_ms == 2000
    assert c.state == 'WAITING_FOR_KEYFRAME'

    # Repeated tick() calls during cooldown do not duplicate requests
    assert c.tick(2001) is None
    assert c.tick(2200) is None
    assert c.tick(2499) is None
    assert c.keyframe_requests_sent == 1
    assert c.last_keyframe_request_at_ms == 2000
    assert c.state == "WAITING_FOR_KEYFRAME"

    # A second keyframe request is allowed at the cooldown boundary (500 ms)
    action = c.tick(2500)
    assert action["type"] == "REQUEST_KEYFRAME"
    assert c.keyframe_requests_sent == 2
    assert c.last_keyframe_request_at_ms == 2500
    assert c.state == "WAITING_FOR_KEYFRAME"

    # A decoded non-keyframe does not recover a waiting stream. State doesn't change to 'HEALTHY'.
    c.on_frame_decoded(2550, is_keyframe=False)

    assert c.last_decoded_frame_at_ms == 2550
    assert c.state == "WAITING_FOR_KEYFRAME"
    assert c.last_keyframe_request_at_ms == 2500

    # A decoded keyframe returns it to HEALTHY
    c.on_frame_decoded(2600, is_keyframe=True)
    assert c.last_decoded_frame_at_ms == 2600
    assert c.state == "HEALTHY"
    assert c.last_keyframe_request_at_ms is None
    assert c.keyframe_requests_sent == 2

    # After recovery, wait a full timeout before another request
    # 1. Only 999 ms since recovered keyframe.
    assert c.tick(3599) is None
    assert c.state == "HEALTHY"
    assert c.keyframe_requests_sent == 2

    # 2. Exactly 1000 ms since the recovered keyframe. Timeout.
    action = c.tick(3600)
    assert action["type"] == "REQUEST_KEYFRAME"
    assert c.state == "WAITING_FOR_KEYFRAME"
    assert c.keyframe_requests_sent == 3
    assert c.last_keyframe_request_at_ms == 3600
    print('All tests pass!')

# What is "Group Of Pictures" (GOP) and Why is it Important?
# https://medium.com/@marketing.veneratech/understanding-gop-what-is-group-of-pictures-and-why-is-it-important-934a756405fe

# A video is composed of a sequence of frames displayed at a given frequency. Though there might be lots of movement in the subject of the content, the background and a large portion of the image is usually the same or very similar from frame to frame.

# Video compression takes advantage of this by only sending some frames in full (known as Inter-frames or I-frames) along with the difference between the I-frame and the subsequent frames. The decoder then uses the I-frame plus these differences to accurately re-create the original frames. This method of compression is known as "temporal compression" because it exploits the fact that information changes in a video slowly over time.

# This brings us back to "Group of Pictures" (GOP). A GOP is the distance between two I-frames measured in number of frames. I-frames are sometimes referred to as "Keyframes" as they are the key that the other types of frames are structured around. Figure 2 below shows a simple representation of a single GOP. It begins with the keyframe (blue) and the white frames contain the info used to create the appearance of motion when referencing the keyframe.

# If you’re watching a compressed video at 30 frames per second (fps), you’re not really seeing 30 full pictures. Instead, you’re seeing sets of GOPs similar to the one shown above. Depending on the codec, a GOP could consist of very large or very small GOP lengths.

# In a typical GOP, you have 3 types of frames: I-frames, P-frames, and B-frames. Every GOP begins with an I-frame, which contain the complete image. After this comes the P-frames (Predicted frames) and B-frames (Bi-directionally predicted frames). P-frames reference past frames and B-frames reference past and future frames. P-frames and B-frames are incomplete images that reference the I-frame and surrounding images to fill in the blanks. P-frames and B-frames contain either bits of new visual information to replace parts of the previous frame or instructions on how to move around bits of the previous frame to create the appearance of motion. By processing and compressing GOPs instead of individual frames, file sizes and stream bitrates can be significantly reduced.

# Your GOP length affects video quality. A shorter duration can preserve more visual information, especially in high-motion video, but is less efficient in that it needs a higher bitrate to look good. A longer GOP is useful in low-motion videos where very little in the frame changes, allowing for reduced redundancy which can look better at lower bitrates. Longer GOPs are better suited for maximum compression on a given bandwidth while smaller GOPs are better suited for scene changes, rewinding, and resiliency to media defects.
