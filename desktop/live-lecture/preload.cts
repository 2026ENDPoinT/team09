import { contextBridge, ipcRenderer } from "electron";
import type { LectureRecord, LiveBridge, LiveEvent } from "../../shared/live-lecture.js";

const bridge: LiveBridge = {
  config: () => ipcRenderer.invoke("ast:live-lecture:config"),
  state: () => ipcRenderer.invoke("ast:live-lecture:state"),
  start: () => ipcRenderer.invoke("ast:live-lecture:start"),
  resume: () => ipcRenderer.invoke("ast:live-lecture:resume"),
  demo: () => ipcRenderer.invoke("ast:live-lecture:demo"),
  audio: (data) => ipcRenderer.send("ast:live-lecture:audio", data),
  pause: () => ipcRenderer.invoke("ast:live-lecture:pause"),
  stop: () => ipcRenderer.invoke("ast:live-lecture:stop"),
  explain: (id, followUp) => ipcRenderer.invoke("ast:live-lecture:explain", { id, followUp }),
  explainRecent: () => ipcRenderer.invoke("ast:live-lecture:explain-recent"),
  explainUtterance: (id) => ipcRenderer.invoke("ast:live-lecture:explain-utterance", id),
  explanation: () => ipcRenderer.invoke("ast:live-lecture:explanation"),
  ask: (question) => ipcRenderer.invoke("ast:live-lecture:ask", question),
  chatView: () => ipcRenderer.invoke("ast:live-lecture:chat-view"),
  setChatOpen: (open) => ipcRenderer.invoke("ast:live-lecture:chat-open", open),
  finishChatClose: (revision) => ipcRenderer.invoke("ast:live-lecture:chat-close-finished", revision),
  captureChatPointer: (capture) => ipcRenderer.invoke("ast:live-lecture:chat-capture-pointer", capture),
  resize: (width, height) => ipcRenderer.invoke("ast:live-lecture:resize", { width, height }),
  close: () => ipcRenderer.invoke("ast:live-lecture:close"),
  subscribe: (listener) => {
    const receive = (_event: Electron.IpcRendererEvent, value: LiveEvent) => listener(value);
    ipcRenderer.on("ast:live-lecture:event", receive);
    return () => ipcRenderer.removeListener("ast:live-lecture:event", receive);
  },
};

if (location.hash.startsWith("#record/")) {
  contextBridge.exposeInMainWorld("lectureRecord", {
    read: () => ipcRenderer.invoke("ast:lecture-record"),
    subscribe(listener: (record: LectureRecord) => void) {
      const receive = (_event: Electron.IpcRendererEvent, record: LectureRecord) => listener(record);
      ipcRenderer.on("ast:lecture-record-changed", receive);
      return () => ipcRenderer.removeListener("ast:lecture-record-changed", receive);
    },
  });
} else {
  contextBridge.exposeInMainWorld("lecture", bridge);
}
