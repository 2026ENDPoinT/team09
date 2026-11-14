export async function prepareMicrophone() {
  let media: MediaStream | undefined;
  let context: AudioContext | undefined;
  try {
    media = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 }, video: false });
    context = new AudioContext({ latencyHint: "interactive" });
    await context.audioWorklet.addModule(new URL("./lecture-capture.js", window.location.href).href);
    await context.resume();
    const source = context.createMediaStreamSource(media);
    const capture = new AudioWorkletNode(context, "lecture-capture", { channelCount: 1, channelCountMode: "explicit" });
    const muted = context.createGain();
    muted.gain.value = 0;
    capture.connect(muted).connect(context.destination);
    const dispose = () => {
      capture.port.close();
      media?.getTracks().forEach((track) => track.stop());
      void context?.close().catch(() => {});
    };
    return {
      start(send: (data: ArrayBuffer) => void, onLost: () => void) {
        capture.port.onmessage = ({ data }) => { if (data instanceof ArrayBuffer) send(data); };
        capture.onprocessorerror = onLost;
        for (const track of media!.getAudioTracks()) track.addEventListener("ended", onLost, { once: true });
        source.connect(capture);
      },
      async stop() {
        source.disconnect();
        await new Promise<void>((resolve) => {
          const done = ({ data }: MessageEvent) => {
            if (data !== "flushed") return;
            clearTimeout(timeout);
            resolve();
          };
          const timeout = setTimeout(resolve, 180);
          capture.port.addEventListener("message", done);
          capture.port.postMessage("flush");
        });
        dispose();
      },
      dispose,
    };
  } catch (error) {
    media?.getTracks().forEach((track) => track.stop());
    void context?.close().catch(() => {});
    throw error;
  }
}
