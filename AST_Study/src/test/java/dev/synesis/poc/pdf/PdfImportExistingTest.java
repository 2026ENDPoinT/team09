package dev.synesis.poc.pdf;

import java.nio.file.*;
import java.time.*;
import java.security.*;
import java.util.*;

public final class PdfImportExistingTest {
    public static void main(String[] args)throws Exception {
        Path base=Files.createTempDirectory("synesis-existing-import-"),root=base.resolve("library"),input=base.resolve("lecture.pdf");
        Files.writeString(input,"same PDF bytes");
        if(PdfImportExisting.find(input,root)!=null || Files.exists(root))throw new AssertionError("Lookup created library state");
        String id=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(input)));
        Path folder=root.resolve(id);Files.createDirectories(folder);Files.copy(input,folder.resolve("source.pdf"));
        Instant added=LocalDate.of(2026,10,4).atStartOfDay(ZoneId.systemDefault()).toInstant();
        Path metadata=folder.resolve("library.properties");Files.writeString(metadata,"addedAt="+added.toEpochMilli()+"\nlastOpenedAt="+Instant.now().toEpochMilli()+"\n");
        var organization=PdfLibraryOrganization.load(root);var course=organization.createFolder("","창사");var child=organization.createFolder(course.id(),"자료");organization.moveDocument(id,child.id());
        Path renamed=base.resolve("different-name.pdf");Files.copy(input,renamed);
        byte[] before=Files.readAllBytes(metadata),orgBefore=Files.readAllBytes(root.resolve("library-organization.json"));
        var found=PdfImportExisting.find(renamed,root);
        if(found==null || !found.location().equals("홈화면 > 창사 > 자료") || !found.addedAt().equals(added) || !found.message().contains("26.10.04"))throw new AssertionError(found);
        if(!Arrays.equals(before,Files.readAllBytes(metadata)) || !Arrays.equals(orgBefore,Files.readAllBytes(root.resolve("library-organization.json"))))throw new AssertionError("Lookup changed existing history");
        Files.writeString(input,"different PDF with same name");if(PdfImportExisting.find(input,root)!=null)throw new AssertionError("Filename mistaken for identity");
        PdfLibraryOrganization.placeImportedDocumentAtHome(root,id);
        if(!PdfImportExisting.find(renamed,root).location().equals("홈화면"))throw new AssertionError("Root placement");
        Files.writeString(metadata,"addedAt=invalid\n");
        if(!PdfImportExisting.find(renamed,root).addedAt().equals(Instant.ofEpochMilli(Files.getLastModifiedTime(folder.resolve("source.pdf")).toMillis())))throw new AssertionError("Legacy fallback");
        System.out.println("PASS: content identity, renamed/same-name PDFs, folder path, original upload date, read-only lookup and legacy date fallback");
    }
}
