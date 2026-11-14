package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.util.List;

/** Offline engine routing/label check; no app windows or paid calls. */
public final class PdfK122RuntimeTest {
    public static void main(String[] args) throws Exception {
        var request=Files.createTempFile("synesis-k122-route-",".json");
        try {
            for(var pair:List.of(new String[]{"newest-k1-2-1","pdf_k121_entry.py"},
                    new String[]{"newest-k1-2-2","pdf_k122_entry.py"})) {
                JsonObject value=new JsonObject();value.addProperty("strategy",pair[0]);Files.writeString(request,value.toString());
                var arguments=List.of("generate","--request",request.toString());
                if(!pair[1].equals(PdfProcess.generationRuntime("pdf_ai.py",arguments)))throw new AssertionError(pair[0]);
                if(!PdfProcess.economyRuntime("pdf_ai.py",arguments))throw new AssertionError("Missing private runtime");
            }
            Files.writeString(request,"{\"strategy\":\"newest-k1-2-0\"}");
            if(PdfProcess.generationRuntime("pdf_ai.py",List.of("generate","--request",request.toString()))!=null)
                throw new AssertionError("Legacy routing changed");
            if(!PdfStudyStrategy.selectable("newest-k1-2-2") || PdfStudyStrategy.ENGINE_IDS.length!=PdfStudyStrategy.ENGINE_LABELS.length)
                throw new AssertionError("Engine picker mismatch");
            if(!"newest-k1-2-5".equals(PdfStudyStrategy.DEFAULT))throw new AssertionError("K1.2.5 must be the default");
        } finally {Files.deleteIfExists(request);}
        System.out.println("PdfK122RuntimeTest passed");
    }
}
