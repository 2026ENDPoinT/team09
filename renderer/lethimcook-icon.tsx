import search from "./assets/let-him-cook/search.svg?no-inline";
import avatar from "./assets/let-him-cook/avatar.svg?no-inline";
import reset from "./assets/let-him-cook/reset.svg?no-inline";
import scope from "./assets/let-him-cook/scope.svg?no-inline";
import chevron from "./assets/let-him-cook/chevron.svg?no-inline";
import reply from "./assets/let-him-cook/reply.svg?no-inline";
import source from "./assets/let-him-cook/source.svg?no-inline";
import external from "./assets/let-him-cook/external.svg?no-inline";
import loadingBack from "./assets/let-him-cook/loadingBack.svg?no-inline";
import loadingFront from "./assets/let-him-cook/loadingFront.svg?no-inline";
import followup from "./assets/let-him-cook/followup.svg?no-inline";
import attach from "./assets/let-him-cook/attach.svg?no-inline";
import send from "./assets/let-him-cook/send.svg?no-inline";

const icons = { search, avatar, reset, scope, chevron, reply, source, external, loadingBack, loadingFront, followup, attach, send };

export function LetHimCookIcon({ name, className }: { name: keyof typeof icons; className?: string }) {
  return <img src={icons[name]} className={className} alt="" draggable={false} />;
}
