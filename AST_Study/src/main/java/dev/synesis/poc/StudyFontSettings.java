package dev.synesis.poc;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;
import java.io.IOException;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/** Defaults shared with the AST settings screen through the account's study directory. */
public record StudyFontSettings(int summaryFont, int tutorFont) {
    public static final int SUMMARY_DEFAULT = 20;
    public static final int TUTOR_DEFAULT = 18;
    public static final int MIN = 6;
    public static final int MAX = 64;
    private static final Gson JSON = new Gson();

    private static Path path() {
        return AppPaths.settings().resolve("study-fonts.json");
    }

    public static StudyFontSettings read(StudyFontSettings fallback) throws IOException {
        String contents;
        try {
            contents = Files.readString(path());
        } catch (NoSuchFileException missing) {
            return fallback;
        }
        try {
            JsonObject values = JSON.fromJson(contents, JsonObject.class);
            return new StudyFontSettings(fontSize(values, "summaryFont"), fontSize(values, "tutorFont"));
        } catch (JsonParseException | ArithmeticException | IllegalStateException | NumberFormatException invalid) {
            throw new IOException("학습 글자 크기 설정을 읽지 못했어요.", invalid);
        }
    }

    private static int fontSize(JsonObject values, String key) {
        var value = values == null ? null : values.get(key);
        if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()) {
            throw new IllegalStateException("Missing font size");
        }
        int size = value.getAsBigDecimal().intValueExact();
        if (size < MIN || size > MAX) throw new IllegalStateException("Invalid font size");
        return size;
    }

    public void save() throws IOException {
        Path target = path();
        Files.createDirectories(target.getParent());
        Path temporary = Files.createTempFile(target.getParent(), "study-fonts-", ".tmp");
        try {
            Files.writeString(temporary, JSON.toJson(this) + "\n");
            try {
                Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException unsupported) {
                Files.move(temporary, target, StandardCopyOption.REPLACE_EXISTING);
            }
        } finally {
            Files.deleteIfExists(temporary);
        }
    }
}
