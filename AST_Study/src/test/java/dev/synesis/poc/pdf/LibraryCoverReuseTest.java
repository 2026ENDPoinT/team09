package dev.synesis.poc.pdf;

import javax.swing.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import org.apache.pdfbox.pdmodel.*;

/** Fixture-only refresh: unchanged covers reuse pixels; changed previews invalidate them. */
public final class LibraryCoverReuseTest {
    public static void main(String[] args)throws Exception{
        Path base=Files.createTempDirectory("synesis-cover-reuse-"),root=base.resolve("library"),file=base.resolve("fixture.pdf");
        try(PDDocument pdf=new PDDocument()){pdf.addPage(new PDPage());pdf.save(file.toFile());}
        String id;try(PdfSource source=PdfSource.open(file,root)){id=source.id;}
        PdfLibraryPanel[] view={null};
        try{
            SwingUtilities.invokeAndWait(()->view[0]=new PdfLibraryPanel(root,path->{},key->CompletableFuture.completedFuture(null),route->{}));
            long until=System.nanoTime()+10_000_000_000L;ImageIcon[] initial={null};
            while(System.nanoTime()<until){
                SwingUtilities.invokeAndWait(()->initial[0]=(ImageIcon)((Map<?,?>)get(view[0],"thumbnails")).get(id));
                if(initial[0]!=null)break;Thread.sleep(20);
            }
            check(initial[0]!=null,"fixture cover not loaded");
            List<PdfLibraryStore.Item> items=PdfLibraryStore.list(root);PdfLibraryStore.Item item=items.get(0);
            Method cover=PdfLibraryPanel.class.getDeclaredMethod("cover",PdfLibraryStore.Item.class);cover.setAccessible(true);
            check(cover.invoke(view[0],item)==initial[0],"unchanged cover was decoded again");
            Path preview=item.source().getParent().resolve("cover-preview-v2.png");
            Files.setLastModifiedTime(preview,java.nio.file.attribute.FileTime.fromMillis(Files.getLastModifiedTime(preview).toMillis()+2000));
            Object refreshed=cover.invoke(view[0],item);check(refreshed!=null&&refreshed!=initial[0],"changed preview reused stale cover");
            check(cover.invoke(view[0],item)==refreshed,"new cover is not reusable");
            System.out.println("LibraryCoverReuseTest passed: repeated refresh reuses cover pixels; preview modification invalidates cache");
        }finally{if(view[0]!=null)SwingUtilities.invokeAndWait(view[0]::close);}
        System.exit(0);
    }
    private static Object get(Object o,String name){try{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}catch(Exception e){throw new RuntimeException(e);}}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
