// Parses the scrcpy v4.0 audio stream (AAC codec) and wraps raw AAC frames in ADTS
// headers so JMuxer can consume them.
//
// Stream format (audio socket, after dummy byte on video socket):
//   [4 bytes]  codec ID — 0x00616163 for AAC, or 0x00000000/0x00000001 to disable stream
//   [packets]  8-byte pts_flags + 4-byte size + size bytes of data
//     - first packet: PACKET_FLAG_CONFIG set → AudioSpecificConfig (2 bytes)
//     - subsequent packets: raw AAC access unit (no ADTS header)
//
// ADTS header (7 bytes, no CRC):
//   FF F1 [profile/freq/ch] [ch/len] [len] [len/fullness] FC

class AudioParser {
    constructor(onFrameCallback) {
        this.buffer = new Uint8Array(0);
        this.codec = null;      // null = not yet read; -1 = disabled; otherwise codec ID
        this.profile = 2;       // AAC-LC (default, overwritten by config packet)
        this.sampleFreqIdx = 3; // 48000 Hz (default)
        this.channelConfig = 2; // stereo (default)
        this.configReceived = false;
        this.onFrameCallback = onFrameCallback;
    }
	
	reset() {
		this.buffer = new Uint8Array(0);
        this.codec = null;      // null = not yet read; -1 = disabled; otherwise codec ID
        this.profile = 2;       // AAC-LC (default, overwritten by config packet)
        this.sampleFreqIdx = 3; // 48000 Hz (default)
        this.channelConfig = 2; // stereo (default)
        this.configReceived = false;
	}

    appendData(data) {
        const buf = new Uint8Array(this.buffer.length + data.length);
        buf.set(this.buffer, 0);
        buf.set(data, this.buffer.length);
        this.buffer = buf;
        this.processBuffer();
    }

    processBuffer() {
        let offset = 0;

        if (this.codec === null) {
            if (this.buffer.length < 4) return;
            const codecId = new DataView(this.buffer.buffer).getUint32(0, false);
            // 0x00000000 = stream gracefully disabled; 0x00000001 = config error
            if (codecId === 0 || codecId === 1) {
                console.warn('Audio stream disabled by server, code:', codecId);
                this.codec = -1;
                this.buffer = new Uint8Array(0);
                return;
            }
            this.codec = codecId;
            console.log('Audio codec ID: 0x' + codecId.toString(16));
            offset = 4;
        }

        if (this.codec === -1) return;

        // Parse packets: 8-byte pts_flags (big-endian) + 4-byte size + data
        while (this.buffer.length - offset >= 12) {
            const view = new DataView(this.buffer.buffer);
			// Streamer.java
			// v3.1 PACKET_FLAG_CONFIG = 1L << 63; in the high 32-bit word that is bit 31 = 0x80000000
            // v4.0 PACKET_FLAG_CONFIG = 1L << 62; in the high 32-bit word that is bit 30 = 0x40000000
            const ptsHigh = view.getUint32(offset, false);
            const isConfig = (ptsHigh & 0x80000000) !== 0;
            const size = view.getInt32(offset + 8, false);

            if (size < 0 || this.buffer.length - offset < 12 + size) break;

            const frameData = this.buffer.slice(offset + 12, offset + 12 + size);
            offset += 12 + size;

            if (isConfig) {
                this.parseAudioConfig(frameData);
            } else if (this.configReceived && size > 0) {
                this.onFrameCallback && this.onFrameCallback(this.wrapInAdts(frameData));
            }
        }

        this.buffer = this.buffer.slice(offset);
    }

    // Parse 2-byte AudioSpecificConfig to extract profile, sampling freq index, channel config.
    // Layout: audioObjectType(5) | samplingFrequencyIndex(4) | channelConfiguration(4) | ...
    parseAudioConfig(configData) {
        if (configData.length < 2) return;
        const b0 = configData[0];
        const b1 = configData[1];
        this.profile = (b0 >> 3) & 0x1F;
        this.sampleFreqIdx = ((b0 & 0x07) << 1) | ((b1 >> 7) & 0x01);
        this.channelConfig = (b1 >> 3) & 0x0F;
        this.configReceived = true;
        console.log('AAC config parsed: profile=' + this.profile +
            ' sampleFreqIdx=' + this.sampleFreqIdx + ' channels=' + this.channelConfig);
    }

    // Prepend a 7-byte ADTS header to a raw AAC access unit.
    wrapInAdts(rawFrame) {
        const frameLength = rawFrame.length + 7; // total ADTS frame = header (7) + payload
        const adts = new Uint8Array(frameLength);
        adts[0] = 0xFF;
        adts[1] = 0xF1; // MPEG-4 | Layer=00 | protection_absent=1
        adts[2] = ((this.profile - 1) << 6) |
                  (this.sampleFreqIdx << 2) |
                  ((this.channelConfig & 4) >> 2);
        adts[3] = ((this.channelConfig & 3) << 6) | ((frameLength >> 11) & 0x03);
        adts[4] = (frameLength >> 3) & 0xFF;
        adts[5] = ((frameLength & 7) << 5) | 0x1F; // buffer_fullness = 0x7FF (VBR), high 6 bits
        adts[6] = 0xFC;                             // buffer_fullness low bits | num_frames-1=0
        adts.set(rawFrame, 7);
        return adts;
    }
}
