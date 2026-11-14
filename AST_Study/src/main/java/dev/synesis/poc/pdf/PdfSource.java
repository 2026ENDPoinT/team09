package dev.synesis.poc.pdf;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.rendering.PDFRenderer;
import java.awt.image.BufferedImage;
import java.awt.Dimension;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.*;
import java.security.*;
import java.util.HexFormat;

/** An immutable local snapshot. PDFBox is used only by the renderer executor. */
final class PdfSource implements AutoCloseable {
    final Path folder;
    final String id;
    volatile String name;
    final int count;
    private final Dimension[] pageSizes;
    private final PDDocument document;
    private final PDFRenderer renderer;

    static PdfSource open(Path input, Path root) throws IOException {
        return open(input, root, null);
    }

    static PdfSource open(Path input, Path root, String displayName) throws IOException {
        String id;
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (var stream = new DigestInputStream(Files.newInputStream(input), digest)) {
                stream.transferTo(OutputStream.nullOutputStream());
            }
            id = HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
        Path folder = root.resolve(id);
        Files.createDirectories(folder);
        Path source = folder.resolve("source.pdf");
        if (!Files.exists(source)) {
            Path temporary = Files.createTempFile(folder, "source-", ".tmp");
            try {
                Files.copy(input, temporary, StandardCopyOption.REPLACE_EXISTING);
                try { Files.move(temporary, source, StandardCopyOption.ATOMIC_MOVE); }
                catch (AtomicMoveNotSupportedException failure) { Files.move(temporary, source, StandardCopyOption.REPLACE_EXISTING); }
            } finally { Files.deleteIfExists(temporary); }
        }
        PDDocument document = Loader.loadPDF(source.toFile());
        if (document.getNumberOfPages() == 0) { document.close(); throw new IOException("빈 PDF입니다."); }
        String name = displayName == null || displayName.isBlank() ? input.getFileName().toString() : displayName;
        try {
            String savedName = PdfLibraryStore.remember(input, folder, document, displayName);
            if (displayName == null || displayName.isBlank()) name = savedName;
        }
        catch (IOException | IllegalArgumentException ignored) { /* Metadata must not hide a readable PDF. */ }
        return new PdfSource(folder, id, name, document);
    }

    private PdfSource(Path folder, String id, String name, PDDocument document) {
        this.folder = folder; this.id = id; this.name = name; this.document = document;
        count = document.getNumberOfPages();
        pageSizes = new Dimension[count];
        for(int page=0;page<count;page++) {
            var box=document.getPage(page).getCropBox();
            pageSizes[page]=new Dimension(Math.max(1,Math.round(box.getWidth())),
                Math.max(1,Math.round(box.getHeight())));
        }
        renderer = new PDFRenderer(document);
        renderer.setSubsamplingAllowed(true);
    }

    synchronized BufferedImage render(int page, float requestedScale) throws IOException {
        var box = document.getPage(page-1).getCropBox();
        float scale = Math.min(requestedScale, (float)Math.sqrt(8_000_000d / (box.getWidth()*box.getHeight())));
        return renderer.renderImage(page-1, scale);
    }

    Dimension pageSize(int page) {
        return pageSizes[page-1];
    }

    @Override public synchronized void close() throws IOException { document.close(); }
}
