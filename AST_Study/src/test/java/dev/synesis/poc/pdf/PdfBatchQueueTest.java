package dev.synesis.poc.pdf;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Local-only batch preflight test. Approval is declined, so no paid API call occurs. */
public final class PdfBatchQueueTest {
    public static void main(String[] args) throws Exception {
        Path directory=Files.createTempDirectory("synesis-batch-test-");
        List<Path> files=new ArrayList<>();
        for(int number=1;number<=3;number++) {
            Path pdf=directory.resolve("lesson-"+number+".pdf");
            try(PDDocument document=new PDDocument()) {
                for(int page=0;page<number;page++)document.addPage(new PDPage());
                document.save(pdf.toFile());
            }
            files.add(pdf);
        }
        CountDownLatch approvals=new CountDownLatch(2);
        List<List<String>> admitted=new ArrayList<>();
        try(PdfBatchQueue queue=new PdfBatchQueue(directory.resolve("library"),plans->{
            synchronized(admitted) {admitted.add(plans.stream().map(PdfBatchQueue.Plan::name).toList());}
            approvals.countDown();
            return null;
        },ignored->{},()->{})) {
            queue.submit(files.subList(0,2));
            queue.submit(files.subList(2,3));
            if(!approvals.await(45,TimeUnit.SECONDS))throw new AssertionError("Batch preflight timed out: "+queue.snapshots());
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
            while(queue.snapshots().stream().anyMatch(s->s.state()==PdfBatchQueue.State.APPROVAL)
                    && System.nanoTime()<deadline)Thread.sleep(10);
            List<PdfBatchQueue.Snapshot> snapshots=queue.snapshots();
            if(snapshots.size()!=3 || snapshots.stream().anyMatch(s->s.state()!=PdfBatchQueue.State.DECLINED))
                throw new AssertionError("Unexpected final states: "+snapshots);
            for(var snapshot:snapshots) {
                try(var requests=Files.list(snapshot.storedPdf().getParent().resolve("requests"))) {
                    for(Path request:requests.filter(p->p.toString().endsWith(".json")).toList()) {
                        var value=com.google.gson.JsonParser.parseString(Files.readString(request)).getAsJsonObject();
                        if(!value.has("strategy") || !"new-concept-v99".equals(value.get("strategy").getAsString()))
                            throw new AssertionError("Batch preflight must request and use NewConceptVer: "+request);
                    }
                }
            }
            synchronized(admitted) {
                if(admitted.size()!=2 || !admitted.get(0).equals(List.of("lesson-1.pdf","lesson-2.pdf"))
                        || !admitted.get(1).equals(List.of("lesson-3.pdf")))
                    throw new AssertionError("Batch approval order: "+admitted);
            }
        }
        System.out.println("PASS: FIFO batch preflight and one approval per batch");
        System.exit(0); // Swing's approval event queue can otherwise keep this standalone smoke process alive.
    }
}
