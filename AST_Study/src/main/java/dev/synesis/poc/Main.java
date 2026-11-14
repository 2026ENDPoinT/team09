package dev.synesis.poc;

import java.nio.file.Files;
import java.nio.file.Path;

public final class Main {
    public static void main(String[] args) throws Exception {
        if (args.length == 0 || !args[0].equals("--render-preview")) {
            AstStudyMain.main(args);
            return;
        }
        if (args.length != 2) throw new IllegalArgumentException("Usage: --render-preview <output.png>");
        // The offline design preview uses its own store.
        Path preview = Files.createTempDirectory("synesis-preview-data-");
        System.setProperty("synesis.appRoot", AppPaths.installedRoot().toString());
        AstStudyMain.prepare(preview.resolve("data"));
        AppDiagnostics.install();
        LectureWindow.renderPreview(Path.of(args[1]));
        System.out.println("Rendered preview: " + args[1]);
        System.exit(0);
    }
}
