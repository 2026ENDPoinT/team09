package dev.synesis.poc.pdf;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.HexFormat;
import java.util.Properties;
import java.util.stream.Collectors;

/** Read-only duplicate lookup using the same content identity as PdfSource. */
final class PdfImportExisting {
    record Saved(String location,Instant addedAt) {
        String message() {
            String date=DateTimeFormatter.ofPattern("yy.MM.dd").withZone(ZoneId.systemDefault()).format(addedAt);
            return "이미 이 파일은 저장되어 있어요!\n["+location+"]에 존재해요.\n업로드일 : "+date;
        }
    }
    static Saved find(Path input,Path root)throws IOException {
        String id;
        try {
            MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try(var stream=new DigestInputStream(Files.newInputStream(input),digest)) {
                stream.transferTo(OutputStream.nullOutputStream());
            }
            id=HexFormat.of().formatHex(digest.digest());
        } catch(NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
        Path folder=root.resolve(id),source=folder.resolve("source.pdf");
        if(!Files.isRegularFile(source,LinkOption.NOFOLLOW_LINKS))return null;
        var organization=PdfLibraryOrganization.load(root);
        String suffix=organization.path(organization.location(id)).stream()
            .map(PdfLibraryOrganization.Folder::name).collect(Collectors.joining(" > "));
        String location="홈화면"+(suffix.isEmpty()?"":" > "+suffix);
        Properties metadata=new Properties();Path file=folder.resolve("library.properties");
        if(Files.isRegularFile(file))try(var stream=Files.newInputStream(file)){metadata.load(stream);}
        long added=Files.getLastModifiedTime(source).toMillis();
        try {added=Long.parseLong(metadata.getProperty("addedAt",Long.toString(added)));}
        catch(NumberFormatException ignored){ /* Legacy metadata falls back to the stored copy's date. */ }
        return new Saved(location,Instant.ofEpochMilli(added));
    }
}
