/// <reference types="vite/client" />
import search from "./assets/dark-mono/search.svg?no-inline";
import leftReflection from "./assets/dark-mono/chat-left-reflection.svg?no-inline";
import bottomReflection from "./assets/dark-mono/chat-bottom-reflection.svg?no-inline";
import avatar from "./assets/dark-mono/chat-avatar.svg?no-inline";
import reset from "./assets/dark-mono/chat-reset.svg?no-inline";
import scope from "./assets/dark-mono/chat-scope.svg?no-inline";
import chevron from "./assets/dark-mono/chat-chevron.svg?no-inline";
import reply from "./assets/dark-mono/chat-reply-avatar.svg?no-inline";
import source from "./assets/dark-mono/chat-source.svg?no-inline";
import external from "./assets/dark-mono/chat-external.svg?no-inline";
import loadingBack from "./assets/dark-mono/chat-loading-back.svg?no-inline";
import loadingFront from "./assets/dark-mono/chat-loading-front.svg?no-inline";
import followup from "./assets/dark-mono/chat-followup.svg?no-inline";
import attach from "./assets/dark-mono/chat-attach.svg?no-inline";
import send from "./assets/dark-mono/chat-send.svg?no-inline";

const icons = { search, leftReflection, bottomReflection, avatar, reset, scope, chevron, reply, source, external, loadingBack, loadingFront, followup, attach, send };

export function DarkMonoIcon({ name, className }: { name: keyof typeof icons; className?: string }) {
  return <img src={icons[name]} className={className} alt="" draggable={false} />;
}
