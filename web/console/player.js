/* WebRTC (WHEP) player for one gateway path, with the wall's self-healing reconnect and back-off. */
"use strict";
class LivePlayer {
  constructor(video, path, onState) {
    this.video = video; this.path = path; this.onState = onState || (() => {});
    this.pc = null; this.retry = 4; this.timer = null; this.closed = false; this.lastFrames = 0; this.stale = 0;
    this.connect();
    this.poller = setInterval(() => this.poll(), 2000);
  }
  async connect() {
    if (this.closed) return;
    this.dispose();
    this.onState("connecting");
    const pc = this.pc = new RTCPeerConnection();
    pc.addTransceiver("video", { direction: "recvonly" });
    pc.ontrack = ev => { this.video.srcObject = ev.streams[0] || new MediaStream([ev.track]); };
    try {
      await pc.setLocalDescription(await pc.createOffer());
      await new Promise(res => {
        if (pc.iceGatheringState === "complete") return res();
        pc.addEventListener("icegatheringstatechange", () => pc.iceGatheringState === "complete" && res());
        setTimeout(res, 1500);
      });
      const r = await fetch(`/stream/${encodeURIComponent(this.path)}/whep`, {
        method: "POST", headers: { "Content-Type": "application/sdp" }, body: pc.localDescription.sdp });
      if (!r.ok) throw new Error(r.status === 404 ? "camera not configured" : `gateway ${r.status}`);
      await pc.setRemoteDescription({ type: "answer", sdp: await r.text() });
    } catch (e) {
      this.onState("error", String(e.message || e));
      this.schedule();
    }
  }
  schedule() {
    if (this.closed) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.connect(), (this.retry + Math.random() * 3) * 1000);
    this.retry = Math.min(60, this.retry * 2);
  }
  async poll() {
    if (!this.pc) return;
    let frames = 0, w = 0, h = 0;
    try {
      (await this.pc.getStats()).forEach(s => {
        if (s.type === "inbound-rtp" && s.kind === "video") { frames = s.framesDecoded || 0; w = s.frameWidth; h = s.frameHeight; }
      });
    } catch (_) { return; }
    if (frames > this.lastFrames) {
      this.stale = 0; this.retry = 4;
      this.onState("playing", w ? `${w}×${h}` : "");
    } else if (frames > 0 || ["failed", "disconnected"].includes(this.pc.connectionState)) {
      this.stale += 2;
      if (this.stale >= 6) { this.onState("frozen"); this.stale = 0; this.schedule(); }
    }
    this.lastFrames = frames;
  }
  // Try again now instead of waiting out the back-off (the wall calls this when the platform comes back).
  nudge() {
    if (this.closed || this.lastFrames > 0) return;
    clearTimeout(this.timer); this.retry = 4; this.connect();
  }
  dispose() { if (this.pc) { this.pc.close(); this.pc = null; } this.lastFrames = 0; }
  close() { this.closed = true; clearTimeout(this.timer); clearInterval(this.poller); this.dispose(); this.video.srcObject = null; }
}
window.LivePlayer = LivePlayer;
