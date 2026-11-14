package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.util.List;

/** Offline route, retained-engine and recovery contract; no application windows. */
public final class PdfK124RuntimeTest {
    public static void main(String[] args) throws Exception {
        var request=Files.createTempFile("synesis-k124-route-",".json");
        try {
            for(var pair:List.of(new String[]{"newest-k1-2-1","pdf_k121_entry.py"},
                    new String[]{"newest-k1-2-2","pdf_k122_entry.py"},
                    new String[]{"newest-k1-2-3","pdf_k123_entry.py"},
                    new String[]{"newest-k1-2-4","pdf_k124_entry.py"},
                    new String[]{"newest-k1-2-5","pdf_k125_entry.py"})) {
                JsonObject value=new JsonObject();value.addProperty("strategy",pair[0]);
                Files.writeString(request,value.toString());
                for(String operation:List.of("generate","recover","prepare-study","group-plan")) {
                    if(!pair[1].equals(PdfProcess.generationRuntime("pdf_ai.py",List.of(operation,"--request",request.toString()))))
                        throw new AssertionError(pair[0]+" / "+operation);
                }
                if(!PdfStudyStrategy.selectable(pair[0]))throw new AssertionError("Missing engine: "+pair[0]);
            }
            if(!PdfWorkspace.readableStudyVersion(PdfStudyStrategy.K1_2_5_PROMPT))
                throw new AssertionError("K1.2.5 saved output rejected");
            if(PdfStudyStrategy.ENGINE_IDS.length!=PdfStudyStrategy.ENGINE_LABELS.length)
                throw new AssertionError("Engine label mismatch");
            JsonObject current=new JsonObject();current.addProperty("strategy","newest-k1-2-5");
            Files.writeString(request,current.toString());
            for(String operation:List.of("tutor","quiz")) {
                if(PdfProcess.generationRuntime("pdf_ai.py",List.of(operation,"--request",request.toString()))!=null)
                    throw new AssertionError("Read-only consumer must keep the shared runtime: "+operation);
            }
            if(!"newest-k1-2-5".equals(PdfStudyStrategy.DEFAULT))throw new AssertionError("K1.2.5 must be the default");
        } finally {Files.deleteIfExists(request);}
        System.out.println("PdfK124RuntimeTest passed");
    }
}
