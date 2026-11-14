import { WebContentsView, type BrowserWindow, type Rectangle } from "electron";

// The website is a native child view, so a DOM overlay in the shell would sit behind it.
export function createWebLoadingView(window: BrowserWindow, htmlPath: string, visible: boolean, onDispose: () => void) {
  const view = new WebContentsView({
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false },
  });
  const contents = view.webContents;
  view.setBackgroundColor("#ffffff");
  view.setVisible(visible);
  window.contentView.addChildView(view);
  let disposed = false;
  let revealing = false;
  let deadline: ReturnType<typeof setTimeout> | undefined;

  function dispose() {
    if (disposed) return;
    disposed = true;
    clearTimeout(deadline);
    if (!window.isDestroyed()) window.contentView.removeChildView(view);
    if (!contents.isDestroyed()) contents.close();
    onDispose();
  }

  contents.setWindowOpenHandler(() => ({ action: "deny" }));
  contents.on("will-navigate", (event) => event.preventDefault());
  contents.on("render-process-gone", dispose);
  const ready = contents.loadFile(htmlPath).then(() => {
    if (!disposed) view.setBackgroundColor("#00000000");
  }).catch(dispose);

  return {
    setVisible(visible: boolean) { if (!disposed) view.setVisible(visible); },
    fit(bounds: Rectangle) {
      if (!disposed) view.setBounds(bounds);
    },
    reveal() {
      if (revealing || disposed) return;
      revealing = true;
      // Release input even if the overlay cannot finish its animation.
      deadline = setTimeout(dispose, 1_500);
      void ready.then(() => {
        if (disposed) return;
        return contents.executeJavaScript(`(() => {
          const screen = document.querySelector(".web-loading-screen");
          screen.classList.add("is-revealing");
          return Promise.allSettled(screen.getAnimations().map((animation) => animation.finished));
        })()`);
      }).then(dispose, dispose);
    },
    dispose,
  };
}
