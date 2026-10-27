# RTP-like Packet Sequence Monitor

# A video stream sends packets with increasing integer sequence numbers: 100, 101, 102, 105, 104, 105

# An RTP packet is split into 2 main sections:
# +--------------------------------------------------------+
# |                      RTP HEADER (metadata)             |
# | (Sequence Number, Timestamp, Payload Type, Sync Source)|
# +--------------------------------------------------------+
# |                      RTP PAYLOAD                       |
# |           (The actual raw audio/video data)            |
# +--------------------------------------------------------+

# Build a class that processes 1 sequence number at a time and tracks:
# 1. received: unique packets accepted
# 2. duplicates: packets seen more than once
# 3. missing: currently missing packets in the observed sequence range, not packets proven permanently lost.
# If a missing package arrives later, I remove it from missing set and count it as out of order.
# 4. out_of_order: newly received packets < highest sequence number seen so far
# 5. highest_sequence: max sequence number seen so far

# Here sequence numbers are ordinary integers. Ignore RTP’s 16-bit wraparound until an interviewer asks about it.

# In real RTP, the sequence number is a 16-bit unsigned integer:
# 65534, 65535, 0, 1, 2

# It wraps around. For first pass, use ordinary integers and say:
# “I’m treating sequence numbers as unbounded integers first. In RTP they are 16-bit and wrap, so I’d add modular sequence comparison and an extended sequence number as a follow-up.”

# Drone camera
# → H.265 encoder
# → RTP packetizer
# → UDP / WebRTC network
# → LiveKit / browser / cloud receiver

# One encoded H.264/H.265 video frame may be split across many RTP packets:

# Video frame 900
# ├── RTP packet 5000
# ├── RTP packet 5001
# └── RTP packet 5002

# If packet 5001 is lost, the receiver may be unable to decode all or part of that video frame. If the lost data is especially important (like part of a keyframe), the video can freeze until the receiver gets another keyframe.

class PacketSequenceMonitor:
    def __init__(self):
        self.received = 0
        self.duplicates = 0
        self.missing_sequences = set()
        self.seen_sequences = set()
        self.out_of_order = 0
        self.highest_sequence = None

    def record(self, seq_num):
        """Process one packet and update counters."""
        if seq_num in self.seen_sequences:
            self.duplicates += 1
            return
        else:
            self.seen_sequences.add(seq_num)
            self.received += 1

        # Record missing sequences
        if self.highest_sequence is not None and seq_num > self.highest_sequence + 1:
            for i in range(self.highest_sequence + 1, seq_num):
                self.missing_sequences.add(i)

        if self.highest_sequence is not None:
            self.highest_sequence = max(self.highest_sequence, seq_num)
        else:
            self.highest_sequence = seq_num

        # Late arriving packet
        if seq_num < self.highest_sequence:
            self.out_of_order += 1
            if seq_num in self.missing_sequences:
                self.missing_sequences.remove(seq_num)
            # If seq_num (ex: 50) < very first sequence (ex: 100),
            # don't add values to self.missing_sequences.
            # Don't create a big artificial missing range from 51 through 99.
            # A sequence number < first observed packet might be a late, reordered, or stale packet.
            # We do not infer an earlier missing range.

    def stats(self):
        """Return a snapshot of current packet-quality counters."""
        return {
            'received': self.received,
            'duplicates': self.duplicates,
            'missing': len(self.missing_sequences),
            'out_of_order': self.out_of_order,
            'highest_sequence': self.highest_sequence,
        }

if __name__ == '__main__':
    m = PacketSequenceMonitor()
    m.record(100)
    assert m.stats() == {
        "received": 1,
        "duplicates": 0,
        "missing": 0,
        "out_of_order": 0,
        "highest_sequence": 100,
    }

    # 3 in-order packets
    m.record(101)
    m.record(102)
    assert m.stats() == {
        "received": 3,
        "duplicates": 0,
        "missing": 0,
        "out_of_order": 0,
        "highest_sequence": 102,
    }
    assert m.seen_sequences == {100, 101, 102}

    # Several missing packets
    m.record(105)
    assert m.stats() == {
        "received": 4,
        "duplicates": 0,
        "missing": 2,
        "out_of_order": 0,
        "highest_sequence": 105,
    }
    assert m.missing_sequences == {103, 104}
    assert m.seen_sequences == {100, 101, 102, 105}

    # Late arriving packet: Delete it from 'missing' and add to 'out_of_order'
    m.record(103)
    assert m.stats() == {
        "received": 5,
        "duplicates": 0,
        "missing": 1,
        "out_of_order": 1,
        "highest_sequence": 105,
    }
    assert m.missing_sequences == {104}
    assert m.seen_sequences == {100, 101, 102, 103, 105}

    # Duplicate in-order packet
    m.record(106)
    m.record(106)
    assert m.stats() == {
        "received": 6,
        "duplicates": 1,
        "missing": 1,
        "out_of_order": 1,
        "highest_sequence": 106,
    }
    assert m.missing_sequences == {104}
    assert m.seen_sequences == {100, 101, 102, 103, 105, 106}

    # Another missing sequence
    m.record(110)
    assert m.stats() == {
        "received": 7,
        "duplicates": 1,
        "missing": 4,
        "out_of_order": 1,
        "highest_sequence": 110,
    }
    assert m.missing_sequences == {104, 107, 108, 109}
    assert m.seen_sequences == {100, 101, 102, 103, 105, 106, 110}

    # Duplicate late packet
    m.record(108)
    m.record(108)
    assert m.stats() == {
        "received": 8,
        "duplicates": 2,
        "missing": 3,
        "out_of_order": 2,
        "highest_sequence": 110,
    }
    assert m.missing_sequences == {104, 107, 109}
    assert m.seen_sequences == {100, 101, 102, 103, 105, 106, 108, 110}

    # Old packet that was never part of observed gap
    # A sequence number < first observed packet might be a late, reordered, or stale packet.
    # We do not infer an earlier missing range. Don't add it to m.missing_sequences.
    m.record(50)
    assert m.stats() == {
        "received": 9,
        "duplicates": 2,
        "missing": 3,   # 50 < first packet. Don't count gap as missing packets.
        "out_of_order": 3,
        "highest_sequence": 110,
    }
    assert m.missing_sequences == {104, 107, 109}
    assert m.seen_sequences == {50, 100, 101, 102, 103, 105, 106, 108, 110}
    print('All tests passed!')

# “Distinguish packets currently missing from packets that were merely late.
# When we observe a packet gap, record the missing sequence numbers.
# If a missing packet arrives later, remove it from the missing_sequence set and count it out of order.
# In production, I'd bound this tracking window so a bad or malicious sequence jump can't consume unbounded memory.”
