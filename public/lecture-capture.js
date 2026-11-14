class LectureCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = 16000 / sampleRate;
    this.weight = 0;
    this.sum = 0;
    this.buffer = new ArrayBuffer(2560);
    this.view = new DataView(this.buffer);
    this.length = 0;
    this.port.onmessage = ({ data }) => {
      if (data !== "flush") return;
      this.flush();
      this.port.postMessage("flushed");
    };
  }

  flush() {
    if (!this.length) return;
    const result = this.length * 2 === this.buffer.byteLength ? this.buffer : this.buffer.slice(0, this.length * 2);
    this.port.postMessage(result, [result]);
    this.buffer = new ArrayBuffer(2560);
    this.view = new DataView(this.buffer);
    this.length = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const sample of input) {
      let weight = this.step;
      while (weight > 0.000001) {
        const take = Math.min(1 - this.weight, weight);
        this.sum += sample * take;
        this.weight += take;
        weight -= take;
        if (this.weight < 0.999999) continue;
        const clamped = Math.max(-1, Math.min(1, this.sum));
        this.view.setInt16(this.length * 2, clamped * (clamped < 0 ? 32768 : 32767), true);
        this.length++;
        if (this.length * 2 === this.buffer.byteLength) this.flush();
        this.sum = 0;
        this.weight = 0;
      }
    }
    return true;
  }
}

registerProcessor("lecture-capture", LectureCapture);
