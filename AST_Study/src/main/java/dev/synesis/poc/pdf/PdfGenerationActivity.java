package dev.synesis.poc.pdf;

import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;

/** File counts for the current view, background views and import queue together. */
public final class PdfGenerationActivity {
    public enum State { RUNNING, WAITING, REVIEW, STOPPED }
    public record Item(String documentId,State state) {}
    public record Counts(long running,long queued,long review,long stopped) {}
    private PdfGenerationActivity() {}

    public static boolean visible(PdfWorkspace.GenerationProgress progress) {
        return progress!=null && (!progress.finished() || progress.needsReview() || progress.failed());
    }
    public static boolean visible(PdfBatchQueue.Snapshot snapshot) {
        return batch(snapshot)!=null;
    }
    public static boolean supersededByBatch(PdfWorkspace.GenerationProgress progress,boolean queued,
                                            Collection<PdfBatchQueue.Snapshot> snapshots) {
        Item view=workspace(progress,queued);
        if(view==null)return false;
        return snapshots.stream().map(PdfGenerationActivity::batch).anyMatch(item->item!=null
            && java.util.Objects.equals(item.documentId(),view.documentId())
            && item.state().ordinal()<view.state().ordinal());
    }

    public static Item workspace(PdfWorkspace.GenerationProgress progress,boolean queued) {
        if(progress==null)return null;
        State state=!progress.finished()?(queued?State.WAITING:State.RUNNING)
            :progress.needsReview()?State.REVIEW:progress.failed()?State.STOPPED:null;
        return state==null?null:new Item(progress.documentId(),state);
    }
    public static Item batch(PdfBatchQueue.Snapshot snapshot) {
        State state=switch(snapshot.state()) {
            case RUNNING -> State.RUNNING;
            case PREPARING,APPROVAL,QUEUED -> State.WAITING;
            case NEEDS_REVIEW -> State.REVIEW;
            case FAILED -> State.STOPPED;
            default -> null;
        };
        String id=snapshot.documentId();
        return state==null?null:new Item(id==null||id.isBlank()?"import:"+snapshot.order():id,state);
    }
    public static Counts count(Collection<Item> items) {
        Map<String,State> files=new LinkedHashMap<>();int anonymous=0;
        for(Item item:items) {
            if(item==null)continue;
            String id=item.documentId();if(id==null||id.isBlank())id="anonymous:"+(anonymous++);
            files.merge(id,item.state(),(left,right)->left.ordinal()<=right.ordinal()?left:right);
        }
        return new Counts(files.values().stream().filter(s->s==State.RUNNING).count(),
            files.values().stream().filter(s->s==State.WAITING).count(),
            files.values().stream().filter(s->s==State.REVIEW).count(),
            files.values().stream().filter(s->s==State.STOPPED).count());
    }
}
