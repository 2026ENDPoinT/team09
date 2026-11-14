package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.FileVisitResult;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Properties;

/** Local PDF copies are the library; metadata only supplies a readable name and dates. */
final class PdfLibraryStore {
    record Item(String id, Path source, String name, Instant addedAt, Instant lastOpenedAt) {}

    private PdfLibraryStore() {}

    static Path defaultRoot() { return dev.synesis.poc.AppPaths.library(); }

    static String remember(Path input, Path folder, PDDocument document) throws IOException {
        return remember(input, folder, document, null);
    }

    static String remember(Path input, Path folder, PDDocument document, String displayName) throws IOException {
        Path metadata = folder.resolve("library.properties");
        Properties values = new Properties();
        if (Files.isRegularFile(metadata)) try (InputStream stream = Files.newInputStream(metadata)) {
            values.load(stream);
        }
        if (displayName != null && !displayName.isBlank()) {
            values.setProperty("name", displayName);
        } else if (values.getProperty("name", "").isBlank()) {
            String name = input.toAbsolutePath().normalize().equals(folder.resolve("source.pdf").toAbsolutePath().normalize())
                    ? pdfTitle(document) : input.getFileName().toString();
            values.setProperty("name", name.isBlank() ? "문서 " + folder.getFileName().toString().substring(0, 8) : name);
        }
        values.putIfAbsent("addedAt", Long.toString(Files.getLastModifiedTime(folder.resolve("source.pdf")).toMillis()));
        values.setProperty("lastOpenedAt", Long.toString(System.currentTimeMillis()));
        values.setProperty("pageCount",Integer.toString(document.getNumberOfPages()));
        Path temporary = Files.createTempFile(folder, "library-", ".tmp");
        try {
            try (OutputStream stream = Files.newOutputStream(temporary)) { values.store(stream, "SYNESIS PDF library"); }
            Files.move(temporary, metadata, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temporary); }
        return PdfLibraryOrganization.load(folder.getParent()).documentName(folder.getFileName().toString(),values.getProperty("name"));
    }

    static List<Item> list(Path root) throws IOException {
        List<Item> result = new ArrayList<>();
        if (!Files.isDirectory(root)) return result;
        PdfLibraryOrganization organization=PdfLibraryOrganization.load(root);
        try (DirectoryStream<Path> folders = Files.newDirectoryStream(root)) {
            for (Path folder : folders) {
                try {
                    String id = folder.getFileName().toString();
                    Path source = folder.resolve("source.pdf");
                    if (!id.matches("[0-9a-f]{64}") || !Files.isRegularFile(source, LinkOption.NOFOLLOW_LINKS)) continue;
                    Properties values = new Properties();
                    Path metadata = folder.resolve("library.properties");
                    if (Files.isRegularFile(metadata)) try (InputStream stream = Files.newInputStream(metadata)) {
                        values.load(stream);
                    } catch (IOException | IllegalArgumentException ignored) { /* Keep the PDF visible. */ }
                    String name = values.getProperty("name", "").strip();
                    if (name.isEmpty()) name = legacyName(folder, source, id);
                    name=organization.documentName(id,name);
                    long modified = Files.getLastModifiedTime(source).toMillis();
                    Instant added = Instant.ofEpochMilli(timestamp(values, "addedAt", modified));
                    Instant opened = Instant.ofEpochMilli(timestamp(values, "lastOpenedAt", modified));
                    result.add(new Item(id, source, name, added, opened));
                } catch (IOException | IllegalArgumentException ignored) { /* One damaged entry must not hide the shelf. */ }
            }
        }
        result.sort(Comparator.comparing(Item::lastOpenedAt).reversed().thenComparing(Item::id));
        return result;
    }

    static void deleteFile(Path root, String id) throws IOException {
        Path folder = storedFolder(root, id);
        // Lecture audio and user-authored notes have independent lifetimes. Keep them when a PDF is removed.
        boolean linked=Files.exists(folder.resolve("recordings")) || Files.exists(folder.resolve("notes"));
        if(!linked)deleteTree(folder);
        else try(var children=Files.list(folder)) {
            for(Path child:children.toList())if(!java.util.Set.of("recordings","notes").contains(child.getFileName().toString()))deleteTree(child);
        }
    }

    static void rename(Path root, String id, String name) throws IOException {
        PdfLibraryOrganization.load(root).renameDocument(id,name);
    }

    static void deleteGeneratedData(Path root, String id) throws IOException {
        Path folder = storedFolder(root, id);
        deleteTree(folder.resolve("generated"));
    }

    private static Path storedFolder(Path root, String id) throws IOException {
        if (id == null || !id.matches("[0-9a-f]{64}")) throw new IOException("문서 식별자가 올바르지 않습니다.");
        Path folder = root.toAbsolutePath().normalize().resolve(id);
        if (!Files.isDirectory(folder, LinkOption.NOFOLLOW_LINKS)
                || !Files.isRegularFile(folder.resolve("source.pdf"), LinkOption.NOFOLLOW_LINKS))
            throw new IOException("저장된 PDF를 찾을 수 없습니다.");
        return folder;
    }

    private static void deleteTree(Path path) throws IOException {
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return;
        Files.walkFileTree(path, new SimpleFileVisitor<>() {
            @Override public FileVisitResult visitFile(Path file, BasicFileAttributes attributes) throws IOException {
                Files.delete(file);
                return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult postVisitDirectory(Path directory, IOException failure) throws IOException {
                if (failure != null) throw failure;
                Files.delete(directory);
                return FileVisitResult.CONTINUE;
            }
        });
    }

    private static long timestamp(Properties values, String key, long fallback) {
        try { return Long.parseLong(values.getProperty(key, "")); }
        catch (NumberFormatException ignored) { return fallback; }
    }

    private static String legacyName(Path folder, Path source, String id) {
        try {
            Path document = folder.resolve("document.json");
            if (Files.isRegularFile(document)) {
                JsonObject data = JsonParser.parseString(Files.readString(document, StandardCharsets.UTF_8)).getAsJsonObject();
                String raw = data.getAsJsonArray("pages").get(0).getAsJsonObject().get("nativeText").getAsString();
                for (String line : raw.split("\\R")) {
                    String text = line.strip();
                    if (text.length() >= 5 && text.length() <= 72 && !text.matches("[0-9 .-]+")) return text;
                }
            }
        } catch (Exception ignored) { /* Fall through to PDF metadata. */ }
        try (PDDocument pdf = Loader.loadPDF(source.toFile())) {
            String title = pdfTitle(pdf);
            if (!title.isBlank()) return title;
        } catch (IOException ignored) { /* The item stays visible so the user can inspect it. */ }
        return "문서 " + id.substring(0, 8);
    }

    private static String pdfTitle(PDDocument document) {
        String title = document.getDocumentInformation().getTitle();
        if (title == null) return "";
        return title.replaceFirst("(?i)^Microsoft Word - ", "")
                .replaceFirst("(?i)\\.docx?$", "").strip();
    }
}
