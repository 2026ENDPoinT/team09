import search from "./assets/focus-mode/search.svg?no-inline";
import avatar from "./assets/focus-mode/avatar.svg?no-inline";
import reset from "./assets/focus-mode/reset.svg?no-inline";
import scope from "./assets/focus-mode/scope.svg?no-inline";
import chevron from "./assets/focus-mode/chevron.svg?no-inline";
import reply from "./assets/focus-mode/reply.svg?no-inline";
import source from "./assets/focus-mode/source.svg?no-inline";
import external from "./assets/focus-mode/external.svg?no-inline";
import loadingBack from "./assets/let-him-cook/loadingBack.svg?no-inline";
import loadingFront from "./assets/focus-mode/loadingFront.svg?no-inline";
import followup from "./assets/focus-mode/followup.svg?no-inline";
import attach from "./assets/focus-mode/attach.svg?no-inline";
import send from "./assets/focus-mode/send.svg?no-inline";

const icons = { search, avatar, reset, scope, chevron, reply, source, external, loadingBack, loadingFront, followup, attach, send };

export function FocusModeIcon({ name }: { name: keyof typeof icons }) {
  return <img src={icons[name]} alt="" draggable={false} />;
}
