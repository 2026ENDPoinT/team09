package dev.synesis.poc.pdf;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import javax.swing.SwingUtilities;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.function.Consumer;

/** Name-ordered studies: parallel local preparation, one document using AI at a time. */
public final class PdfBatchQueue implements AutoCloseable {
    public enum State { PREPARING, APPROVAL, QUEUED, RUNNING, COMPLETE, NEEDS_REVIEW, FAILED, DECLINED, CANCELLED }
    public record Snapshot(long order,String documentId,String name,Path storedPdf,State state,
                           int percent,String stage,double estimatedUsd,String strategy) {
        public Snapshot(long order,String documentId,String name,Path storedPdf,State state,int percent,String stage,double estimatedUsd) {
            this(order,documentId,name,storedPdf,state,percent,stage,estimatedUsd,PdfStudyStrategy.DEFAULT);
        }
    }
    public record Plan(String name,int pages,double estimatedUsd) {}
    public record ImportChoice(Path file,String destination,boolean autoGenerate,String strategy) {
        public ImportChoice(Path file,String destination,boolean autoGenerate){this(file,destination,autoGenerate,PdfStudyStrategy.DEFAULT);}
        public ImportChoice {
            java.util.Objects.requireNonNull(file);java.util.Objects.requireNonNull(destination);
            if(!PdfStudyStrategy.selectable(strategy))throw new IllegalArgumentException("Unknown study engine: "+strategy);
        }
    }
    @FunctionalInterface public interface Approval { List<Double> approve(List<Plan> plans); }

    private static final Gson JSON = new Gson();
    private static final int MAX_ACTIVE_FILES = 8;
    private final Path root;
    private final ExecutorService workers = Executors.newFixedThreadPool(MAX_ACTIVE_FILES,
        job -> {Thread thread=new Thread(job,"pdf-batch-worker");thread.setDaemon(true);return thread;});
    private final ExecutorService admissions = Executors.newSingleThreadExecutor(
        job -> {Thread thread=new Thread(job,"pdf-batch-admission");thread.setDaemon(true);return thread;});
    @FunctionalInterface interface Runner {
        void run(PdfProcess process,String script,List<String> arguments,Consumer<JsonObject> events) throws Exception;
    }
    private final Runner runner;
    private final Approval approval;
    private final Consumer<List<Snapshot>> listener;
    private volatile java.util.function.BiConsumer<Snapshot,JsonObject> studyListener=(snapshot,event)->{};
    public void setStudyListener(java.util.function.BiConsumer<Snapshot,JsonObject> listener) {
        studyListener=java.util.Objects.requireNonNull(listener);
    }
    public static boolean active(State state) {
        return state==State.PREPARING || state==State.APPROVAL || state==State.QUEUED || state==State.RUNNING;
    }
    static Snapshot preferredSnapshot(List<Snapshot> matches) {
        return matches.stream().max(java.util.Comparator.<Snapshot,Boolean>comparing(s->active(s.state()))
            .thenComparingLong(Snapshot::order)).orElse(null);
    }
    private final Runnable libraryRefresh;
    private final List<Task> tasks=new ArrayList<>();
    private boolean closed;
    private long nextOrder;
    private final boolean paidGrouping;

    private static final class Task {
        final long order;
        final Path original;
        final PdfProcess process=new PdfProcess();
        volatile Path storedPdf,folder;
        volatile String documentId,name,stage="PDF 준비 대기";
        volatile State state=State.PREPARING;
        volatile int percent;
        volatile boolean firstSummaryShown;
        volatile double estimate;
        volatile JsonObject estimateDetails;
        volatile boolean cancelled;
        boolean importAtHome;
        String destination;
        boolean autoGenerate=true;
        String strategy=PdfStudyStrategy.DEFAULT;
        JsonObject overviewEvent;
        final java.util.Map<Integer,JsonObject> unitEvents=new java.util.TreeMap<>();
        volatile Future<?> prepareFuture,analysisFuture;
        Task(long order,Path path){this.order=order;original=path;name=path.getFileName().toString();}
        Snapshot snapshot(){
            boolean running=state==State.RUNNING;
            return new Snapshot(order,documentId,name,storedPdf,state,
                running?StudyLoadingProgress.display(percent,firstSummaryShown):percent,
                running?(firstSummaryShown?"전체 생성 · ":"첫 요약 준비 · ")+stage:stage,estimate,strategy);
        }
    }

    public PdfBatchQueue(Approval approval,Consumer<List<Snapshot>> listener,Runnable libraryRefresh) {
        this(PdfLibraryStore.defaultRoot(),approval,listener,libraryRefresh,true);
    }

    PdfBatchQueue(Path root,Approval approval,Consumer<List<Snapshot>> listener,Runnable libraryRefresh) {
        this(root,approval,listener,libraryRefresh,false); // Explicit local-only fixture/preflight path.
    }

    private PdfBatchQueue(Path root,Approval approval,Consumer<List<Snapshot>> listener,Runnable libraryRefresh,boolean paidGrouping) {
        this(root,approval,listener,libraryRefresh,paidGrouping,(process,script,args,events)->process.run(script,args,process.ticket(),events));
    }
    PdfBatchQueue(Path root,Approval approval,Consumer<List<Snapshot>> listener,Runnable libraryRefresh,boolean paidGrouping,Runner runner) {
        this.runner=runner;
        this.root=root;this.approval=approval;this.listener=listener;this.libraryRefresh=libraryRefresh;
        this.paidGrouping=paidGrouping;
    }

    public synchronized void submit(List<Path> files) {
        submit(files,false);
    }

    public synchronized void submitAtHome(List<Path> files) {
        submit(files,true);
    }

    private synchronized void submit(List<Path> files,boolean atHome) {
        submitChoices(files.stream().filter(java.util.Objects::nonNull).map(path->new ImportChoice(path,"",true)).toList(),atHome);
    }

    public synchronized void submitImports(List<ImportChoice> choices) {
        submitChoices(choices,true);
    }

    private synchronized void submitChoices(List<ImportChoice> choices,boolean place) {
        List<Path> files=choices.stream().filter(java.util.Objects::nonNull).map(ImportChoice::file).toList();
        if(closed || files.isEmpty())return;
        List<Task> batch=new ArrayList<>();
        for(Path path:orderedFiles(files)) {
            if(path==null || !Files.isRegularFile(path) ||
                !path.getFileName().toString().toLowerCase(java.util.Locale.ROOT).endsWith(".pdf"))continue;
            Task task=new Task(++nextOrder,path.toAbsolutePath().normalize());
            ImportChoice choice=choices.stream().filter(c->c!=null && c.file().equals(path)).findFirst().orElseThrow();
            task.importAtHome=place;task.destination=choice.destination();task.autoGenerate=choice.autoGenerate();task.strategy=choice.strategy();
            tasks.add(task);batch.add(task);
        }
        if(batch.isEmpty())return;
        publish();
        // Start local work immediately, including batches submitted while AI is busy.
        for(Task task:batch)task.prepareFuture=workers.submit(()->prepare(task));
        if(paidGrouping)for(Task task:batch)task.analysisFuture=admissions.submit(()->processPrepared(task));
        else admissions.execute(()->prepareAndAdmit(batch));
    }

    public synchronized List<Snapshot> snapshots(){return tasks.stream().map(Task::snapshot).toList();}

    public synchronized Snapshot forStoredPdf(Path path) {
        Path normalized=path.toAbsolutePath().normalize();
        return preferredSnapshot(tasks.stream().filter(task->task.original.equals(normalized)
            || task.storedPdf!=null && task.storedPdf.equals(normalized)).map(Task::snapshot).toList());
    }

    /** Replay only the latest display state; provider responses remain on disk. */
    public synchronized void replayStudy(Path path) {
        Snapshot selected=forStoredPdf(path);
        if(selected==null || !active(selected.state()))return;
        for(Task task:tasks)if(task.order==selected.order()) {
            if(task.overviewEvent!=null)deliverStudy(selected,task.overviewEvent);
            task.unitEvents.values().forEach(event->deliverStudy(selected,event));
            return;
        }
    }
    private synchronized void forwardStudy(Task task,JsonObject event) {
        String type=string(event,"type");
        if(!List.of("summary_overview_ready","summary_overview_delta","summary_unit_delta","summary_unit_ready").contains(type))return;
        if(!task.strategy.equals(string(event,"strategy")))return;
        JsonObject retained=event.deepCopy();
        if(!task.firstSummaryShown && !(event.has("discard")&&event.get("discard").getAsBoolean())) {
            try {
                JsonObject content=event.has("overview")&&event.get("overview").isJsonObject()?event.getAsJsonObject("overview"):event.has("summary") && event.get("summary").isJsonObject()
                    ?event.getAsJsonObject("summary"):null;
                if(content==null && event.has("path")) {
                    Path path=Path.of(string(event,"path")).toAbsolutePath().normalize();
                    if(task.folder!=null && path.startsWith(task.folder.toAbsolutePath().normalize())) {
                        JsonObject saved=read(path);
                        String field=type.equals("summary_overview_ready")?"overview":"summary";
                        if(saved.has(field)&&saved.get(field).isJsonObject())content=saved.getAsJsonObject(field);
                    }
                }
                if(content!=null && !string(content,"body").isBlank()
                        && !(content.has("studyContentSkipped")&&content.get("studyContentSkipped").getAsBoolean())) {
                    task.firstSummaryShown=true;publish();
                }
            }catch(Exception ignored){ /* Canonical completion remains the recovery path. */ }
        }
        if(type.equals("summary_overview_ready"))task.overviewEvent=retained;
        else if(type.equals("summary_overview_delta")) {
            if(task.overviewEvent==null || !string(task.overviewEvent,"type").equals("summary_overview_ready"))task.overviewEvent=retained;
        }
        else if(event.has("unit")) {
            int number=event.get("unit").getAsInt();
            JsonObject previous=task.unitEvents.get(number);
            if(previous==null || !string(previous,"type").equals("summary_unit_ready") || type.equals("summary_unit_ready"))
                task.unitEvents.put(number,retained);
        }
        deliverStudy(task.snapshot(),retained);
    }
    private void deliverStudy(Snapshot snapshot,JsonObject event) {
        JsonObject copy=event.deepCopy();
        SwingUtilities.invokeLater(()->studyListener.accept(snapshot,copy));
    }

    public synchronized Path pathFor(long order) {
        for(Task task:tasks)if(task.order==order)
            return task.storedPdf==null?task.original:task.storedPdf;
        return null;
    }

    static List<Path> orderedFiles(List<Path> files) {
        return files.stream().filter(java.util.Objects::nonNull).sorted((a,b)->{
            String left=a.getFileName().toString(),right=b.getFileName().toString();
            int compared=left.compareToIgnoreCase(right);
            if(compared==0)compared=left.compareTo(right);
            return compared!=0?compared:a.toAbsolutePath().toString().compareTo(b.toAbsolutePath().toString());
        }).toList();
    }

    private void processPrepared(Task task) {
        try {
            task.prepareFuture.get();
            if(task.cancelled||task.state!=State.QUEUED)return;
            var permit=PdfStudyQueue.global().acquire();
            try {
                if(task.cancelled)return;
                update(task,State.RUNNING,0,"조각 묶음 판단 중 · API 비용이 발생해요");
                preparePlan(task,true);
                if(!task.cancelled)analyze(task,1.0);
            }finally {task.process.afterIdle(permit::close);}
        } catch(Exception error){if(!task.cancelled)fail(task,error);}
    }

    private void prepareAndAdmit(List<Task> batch) {
        for(Task task:batch) {
            try {task.prepareFuture.get();}
            catch(Exception error) {if(!task.cancelled)fail(task,error);}
        }
        List<Task> ready=batch.stream().filter(task->task.state==State.APPROVAL && !task.cancelled).toList();
        if(ready.isEmpty())return;
        List<Plan> plans=ready.stream().map(task->new Plan(task.name,taskPageCount(task),task.estimate)).toList();
        List<Double> budgets=null;
        try {
            if(paidGrouping)budgets=ready.stream().map(task->1.0).toList();
            else if(SwingUtilities.isEventDispatchThread())budgets=approval.approve(plans);
            else {
                @SuppressWarnings("unchecked") List<Double>[] answer=new List[1];
                SwingUtilities.invokeAndWait(()->answer[0]=approval.approve(plans));
                budgets=answer[0];
            }
        } catch(Exception error) {for(Task task:ready)fail(task,error);return;}
        if(budgets==null) {
            for(Task task:ready)update(task,State.DECLINED,0,"강의 해설 생성 승인 취소");
            return;
        }
        if(budgets.size()!=ready.size()) {
            for(Task task:ready)fail(task,new IllegalArgumentException("파일별 비용 한도가 누락됐어요."));
            return;
        }
        for(int index=0;index<ready.size();index++) {
            Task task=ready.get(index);
            if(task.cancelled)continue;
            update(task,State.QUEUED,0,"앞선 PDF 작업 대기 중");
            double budget=budgets.get(index);
            task.analysisFuture=admissions.submit(()->{
                try {
                    var permit=PdfStudyQueue.global().acquire();
                    try {if(!task.cancelled)analyze(task,budget);}
                    finally {task.process.afterIdle(permit::close);}
                }catch(InterruptedException interrupted){Thread.currentThread().interrupt();}
            });
        }
    }

    private void prepare(Task task) {
        if(task.cancelled)return;
        update(task,State.PREPARING,0,"PDF 복제본 저장 중");
        try {
            try(PdfSource source=PdfSource.open(task.original,root)) {
                task.folder=source.folder;task.documentId=source.id;task.name=source.name;
                task.storedPdf=source.folder.resolve("source.pdf").toAbsolutePath().normalize();
            }
            synchronized(this) {
                boolean duplicate=task.autoGenerate && tasks.stream().anyMatch(previous->previous.order<task.order && previous.autoGenerate
                    && task.documentId.equals(previous.documentId) && task.strategy.equals(previous.strategy)
                    && previous.state!=State.FAILED && previous.state!=State.CANCELLED);
                if(duplicate) {
                    update(task,State.DECLINED,0,"같은 PDF가 앞선 작업에 있어요");
                    return;
                }
            }
            if(task.importAtHome)PdfLibraryOrganization.placeImportedDocument(root,task.documentId,task.destination);
            SwingUtilities.invokeLater(libraryRefresh);
            if(task.cancelled)return;
            if(!task.autoGenerate) {
                update(task,State.COMPLETE,100,"PDF 불러오기 완료 · 자동 생성 끔");
                return;
            }
            update(task,State.PREPARING,0,"페이지 원문 준비 중");
            runner.run(task.process,"pdf_pipeline.py",List.of("prepare","--folder",task.folder.toString()),
                event->{
                    if("progress".equals(string(event,"type")))
                        update(task,State.PREPARING,0,"페이지 원문 준비 · "+string(event,"stage"));
                });
            if(task.cancelled)return;
            if(paidGrouping) {
                JsonObject local=new JsonObject();local.addProperty("strategy",task.strategy);
                local.addProperty("scope","document");local.addProperty("page",0);
                Path request=writeRequest(task,local);
                update(task,State.PREPARING,0,"원문 조각 분리 중 · 로컬 처리");
                runner.run(task.process,"pdf_ai.py",List.of("prepare-study","--folder",task.folder.toString(),
                    "--request",request.toString()),event->{});
                if(!task.cancelled)update(task,State.QUEUED,0,"로컬 준비 완료 · 앞선 PDF 분석 대기");
            } else {
                preparePlan(task,false);
                update(task,State.APPROVAL,0,"묶음 비용 확인 대기");
            }
        } catch(Exception error) {if(!task.cancelled)fail(task,error);}
    }

    private void preparePlan(Task task,boolean remote) throws Exception {
        JsonObject document=read(task.folder.resolve("document.json"));
        JsonObject planRequest=new JsonObject();
        JsonArray pages=new JsonArray();
        int count=document.getAsJsonArray("pages").size();
        for(int number=1;number<=count;number++)pages.add(number);
        planRequest.add("pages",pages);planRequest.addProperty("scope","document");
        planRequest.addProperty("page",0);planRequest.addProperty("strategy",task.strategy);
        planRequest.addProperty("retryMissingResponses",true);
        Path request=writeRequest(task,planRequest);
        List<String> planArgs=new java.util.ArrayList<>(List.of(remote?"group-plan":"vision-plan",
            "--folder",task.folder.toString(),"--request",request.toString()));
        if(remote)planArgs.addAll(List.of("--allow-remote","--model","gpt-6-luna","--max-usd","1.0"));
        runner.run(task.process,"pdf_ai.py",planArgs,event->{});
        JsonObject plan=read(resultPath(request));
        task.estimate=plan.get("totalCostEstimateUsd").getAsDouble();
        task.estimateDetails=plan.deepCopy();
    }

    private void analyze(Task task,double budget) {
        if(task.cancelled)return;
        update(task,State.RUNNING,0,"강의 해설 준비 중");
        try {
            JsonObject request=new JsonObject();
            request.addProperty("scope","document");request.addProperty("page",0);
            request.addProperty("strategy",task.strategy);
            request.addProperty("retryMissingResponses",true);
            if(task.estimateDetails!=null && task.estimateDetails.has("pendingOriginalUsage")) {
                JsonObject pending=task.estimateDetails.getAsJsonObject("pendingOriginalUsage");
                if(pending.has("requests") && pending.get("requests").getAsInt()>0)
                    request.addProperty("retryUnresolvedResponses",true);
            }
            request.addProperty("approvedEstimateUsd",task.estimate);
            if(task.estimateDetails!=null)
                for(String field:new String[]{"estimateLowUsd","estimateHighUsd","estimateBasis","estimateVersion"})
                    if(task.estimateDetails.has(field))request.add(field,task.estimateDetails.get(field).deepCopy());
            Path requestPath=writeRequest(task,request);
            runner.run(task.process,"pdf_ai.py",List.of("generate","--folder",task.folder.toString(),
                "--request",requestPath.toString(),"--allow-remote","--model","gpt-6-luna",
                "--max-usd",Double.toString(budget)),event->{
                    forwardStudy(task,event);
                    if("study_timeline".equals(string(event,"type")) && event.has("percent")) {
                        update(task,State.RUNNING,Math.max(task.percent,Math.min(99,event.get("percent").getAsInt())),string(event,"stage"));
                    }
                    if("progress".equals(string(event,"type"))) {
                        String stage=string(event,"stage");
                        int current=event.get("page").getAsInt(),total=event.get("total").getAsInt();
                        update(task,State.RUNNING,Math.max(task.percent,
                            PdfWorkspace.generationPercent(stage,current,total)),stage);
                    }
                });
            if(task.cancelled)return;
            JsonObject result=read(resultPath(requestPath));
            int pending=PdfWorkspace.pendingStudyPageCount(result);
            if(result.has("creditStopped") && result.get("creditStopped").getAsBoolean()) {
                update(task,State.NEEDS_REVIEW,Math.min(99,task.percent),"크레딧 부족으로 생성 중단 · 완료된 강의 해설 보관됨");
                SwingUtilities.invokeLater(()->CreditShortageDialog.show(null,"크레딧이 부족해서 강의 해설/개념 정리 생성이 중단됐어요. 완료된 내용은 보관했어요."));
            }
            else if("partial".equals(string(result,"kind")))
                update(task,State.NEEDS_REVIEW,Math.min(99,task.percent),"생성 일부 중단 · 남은 영역 확인 필요");
            else if(pending>0)
                update(task,State.NEEDS_REVIEW,100,"강의 해설 생성 완료 · 원문 확인 필요 "+pending+"쪽");
            else update(task,State.COMPLETE,100,"강의 해설·개념 정리 완료");
        } catch(Exception error) {if(!task.cancelled)fail(task,error);}
    }

    private static int taskPageCount(Task task) {
        try {return read(task.folder.resolve("document.json")).getAsJsonArray("pages").size();}
        catch(Exception ignored) {return 0;}
    }
    private Path writeRequest(Task task,JsonObject request) throws Exception {
        Path path=task.folder.resolve("requests/"+UUID.randomUUID()+".json");
        Files.createDirectories(path.getParent());
        Files.writeString(path,JSON.toJson(request),StandardCharsets.UTF_8);
        return path;
    }
    private static Path resultPath(Path request) {
        return request.resolveSibling(request.getFileName().toString().replace(".json",".result.json"));
    }
    private static JsonObject read(Path path) throws Exception {
        try(var reader=Files.newBufferedReader(path,StandardCharsets.UTF_8)) {
            return JsonParser.parseReader(reader).getAsJsonObject();
        }
    }
    private static String string(JsonObject value,String key) {
        return value.has(key)?value.get(key).getAsString():"";
    }
    private void fail(Task task,Exception error) {
        if(error.getMessage()!=null && error.getMessage().contains("크레딧이 부족해서"))
            SwingUtilities.invokeLater(()->CreditShortageDialog.show(null,error.getMessage()));
        update(task,State.FAILED,task.percent,"중단 · "+
            (error.getMessage()==null?error.getClass().getSimpleName():error.getMessage()));
    }
    private void update(Task task,State state,int percent,String stage) {
        if(task.cancelled && state!=State.CANCELLED)return;
        task.state=state;task.percent=percent;task.stage=stage;
        publish();
    }
    private void publish() {
        List<Snapshot> current=snapshots();
        SwingUtilities.invokeLater(()->listener.accept(current));
    }

    public CompletableFuture<Void> releaseDocument(String documentId) {
        List<Task> affected;
        synchronized(this) {affected=tasks.stream().filter(t->documentId.equals(t.documentId)).toList();}
        for(Task task:affected) {
            task.cancelled=true;task.process.cancel();
            if(task.prepareFuture!=null)task.prepareFuture.cancel(false);
            if(task.analysisFuture!=null)task.analysisFuture.cancel(false);
            update(task,State.CANCELLED,task.percent,"작업 취소");
        }
        return CompletableFuture.runAsync(()->{
            for(Task task:affected) {
                for(Future<?> future:new Future<?>[]{task.prepareFuture,task.analysisFuture}) {
                    if(future==null)continue;
                    try {future.get();}catch(Exception ignored) {}
                }
            }
        });
    }

    @Override public synchronized void close() {
        if(closed)return;
        closed=true;
        for(Task task:tasks) {task.cancelled=true;task.process.close();}
        admissions.shutdownNow();workers.shutdownNow();
    }
}
