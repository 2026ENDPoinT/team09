package dev.synesis.poc.pdf;

import java.util.*;

public final class PdfGenerationActivityTest {
    static PdfWorkspace.GenerationProgress progress(String id,boolean finished,boolean failed,boolean review) {
        return new PdfWorkspace.GenerationProgress(id,id,finished?99:89,"원래 진행",finished,failed,review);
    }
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args) {
        check(PdfGenerationActivity.visible(new PdfWorkspace.GenerationProgress("review","review",100,"완료·검토 필요",true,false,true)),"100% review hidden");
        check(PdfGenerationActivity.visible(new PdfBatchQueue.Snapshot(9,"review","review",null,PdfBatchQueue.State.NEEDS_REVIEW,100,"검토",0)),"100% batch review hidden");
        check(!PdfGenerationActivity.visible(new PdfWorkspace.GenerationProgress("done","done",100,"완료",true,false,false)),"Completed result retained in activity");
        var current=PdfGenerationActivity.workspace(progress("current",false,false,false),false);
        var background=PdfGenerationActivity.workspace(progress("background",false,false,false),false);
        check(PdfGenerationActivity.count(List.of(current,background)).running()==2,"Current file omitted from running count");
        var queued=PdfGenerationActivity.workspace(progress("queued",false,false,false),true);
        var preparing=PdfGenerationActivity.batch(new PdfBatchQueue.Snapshot(1,"upload","upload",null,PdfBatchQueue.State.PREPARING,0,"원문 준비",0));
        var review=PdfGenerationActivity.workspace(progress("review",true,false,true),false);
        check(PdfGenerationActivity.supersededByBatch(progress("review",true,false,true),false,
            List.of(new PdfBatchQueue.Snapshot(3,"review","review",null,PdfBatchQueue.State.RUNNING,15,"생성 중",0))),"Old review hid a running batch");
        var failed=PdfGenerationActivity.workspace(progress("failed",true,true,false),false);
        var counts=PdfGenerationActivity.count(Arrays.asList(current,queued,preparing,review,failed,null));
        check(counts.equals(new PdfGenerationActivity.Counts(1,2,1,1)),"Waiting/preparation/review counted as generation: "+counts);
        var duplicate=PdfGenerationActivity.batch(new PdfBatchQueue.Snapshot(2,"current","same file",null,PdfBatchQueue.State.QUEUED,0,"대기",0));
        check(PdfGenerationActivity.count(List.of(current,duplicate)).equals(new PdfGenerationActivity.Counts(1,0,0,0)),"Duplicate document counted twice");
        check(PdfGenerationActivity.workspace(progress("done",true,false,false),false)==null,"Completed file counted");
        System.out.println("PdfGenerationActivityTest passed: foreground/background/import totals, waiting states, terminal states and document deduplication");
    }
}
