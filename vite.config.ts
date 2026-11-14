import { defineConfig } from "vite";

export default defineConfig({
  base: "./", envDir: false,
  build: { rolldownOptions: { input: {
    main: "index.html", assignment: "assignment-browser.html", webLoading: "web-loading/index.html", liveLecture: "live-lecture.html",
  } } },
});
