package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Local workbook history and answer-state checks; no window or provider calls. */
public final class QuizWorkbookStoreTest {
    private static final Gson JSON=new Gson();
    private static final String DOC="workbook-document";

    public static void main(String[] args) throws Exception {
        metadataAndStableLegacyIdentity();
        purposeLabelsPreserveLegacyProfiles();
        historyLoadsEveryValidRunWithoutDuplicates();
        answerStateIsScopedAndPreservesRawText();
        catalogNamesAndDeletion();
        System.out.println("QuizWorkbookStoreTest passed: workbook metadata, all saved runs, legacy identity, source compatibility, atomic answer state, and document/workbook isolation. No paid calls.");
    }

    private static void metadataAndStableLegacyIdentity() {
        JsonObject value=result("run-a",1_792_701_000_000L,"practice_set");
        QuizWorkbook book=QuizWorkbook.fromResult(value);
        equal(book.id(),"run-a","run identity");equal(book.theme(),QuizPanel.Theme.PRACTICE,"N제 theme");
        equal(book.difficulty(),"중상","difficulty");equal(book.requestedCount(),3,"requested count");
        equal(book.totalUsd(),.012,"usage-derived cost");equal(book.elapsedSeconds(),11.5,"elapsed time");
        require(book.title().startsWith(QuizPanel.Theme.PRACTICE.title+" 문제집 · "),"generated workbook title");
        // 2026-10-22 20:30:00 UTC = 2026-10-23 05:30:00 in Seoul.
        equal(book.title(),QuizPanel.Theme.PRACTICE.title+" 문제집 · 10.23 05:30:00","title uses Asia/Seoul rather than host timezone");
        try {book.questions().clear();throw new AssertionError("questions were mutable");}catch(UnsupportedOperationException expected) {}
        JsonObject legacy=value.deepCopy();legacy.remove("quizRunId");
        equal(QuizWorkbook.fromResult(legacy).id(),QuizWorkbook.fromResult(legacy.deepCopy()).id(),"legacy identity is stable across opens and copies");
        JsonObject unknownCost=value.deepCopy();unknownCost.getAsJsonObject("runUsage").addProperty("unknownUsageRequests",1);
        require(QuizWorkbook.fromResult(unknownCost).totalUsd()==null,"unknown charges are not represented as free");
        JsonObject empty=value.deepCopy();empty.add("questions",new JsonArray());empty.addProperty("unfilled",3);
        fail(()->QuizWorkbook.fromResult(empty),"a failed zero-question attempt is not a workbook");
    }

    private static void purposeLabelsPreserveLegacyProfiles() {
        for(QuizPanel.Theme theme:QuizPanel.Theme.values())
            equal(theme.profileTargetDescription(),theme==QuizPanel.Theme.CONCEPT?"기본 개념 확인":"일반·심화 목표 5:5","new configuration purpose");
        JsonObject raw=result("legacy-mixed",1000,"concept_completion");
        raw.getAsJsonArray("questions").get(0).getAsJsonObject().addProperty("profile","general");
        raw.getAsJsonArray("questions").get(1).getAsJsonObject().addProperty("profile","advanced");
        JsonObject before=raw.deepCopy();
        QuizWorkbook book=QuizWorkbook.fromResult(raw);
        equal(book.levelDescription(),"기본 개념 확인","legacy concept uses neutral purpose");
        equal(book.questions().get(1).profile(),"advanced","legacy advanced is not relabeled");
        equal(raw,before,"display does not rewrite saved result");
        raw.getAsJsonObject("quiz").addProperty("theme","understanding");
        equal(QuizWorkbook.fromResult(raw).levelDescription(),"일반 1 · 심화 1 · 미지정 1 (적합성 미확인)","saved profile counts not invented ratio");
        equal(QuizWorkbook.fromResult(result("legacy-no-profile",1000,"recall")).levelDescription(),"난이도 중상","legacy difficulty remains");
    }

    private static void historyLoadsEveryValidRunWithoutDuplicates() throws Exception {
        Path folder=Files.createTempDirectory("quiz-workbook-history-");
        try {
            Path root=folder.resolve("generated/quiz-v2");
            JsonObject first=result("first",1000,"concept_completion"),second=result("second",2000,"recall");
            write(root.resolve("runs/first.json"),first);write(root.resolve("runs/second.json"),second);
            write(root.resolve("latest.json"),second);
            JsonObject partial=first.deepCopy();partial.addProperty("completedAtMs",1100);
            partial.getAsJsonArray("questions").remove(2);partial.addProperty("unfilled",1);
            write(root.resolve("runs/older-first-snapshot.json"),partial);
            JsonObject zero=result("empty",3000,"recall");zero.add("questions",new JsonArray());zero.addProperty("unfilled",3);
            write(root.resolve("runs/empty.json"),zero);
            JsonObject foreign=result("foreign",4000,"recall");foreign.addProperty("documentId","different");
            write(root.resolve("runs/foreign.json"),foreign);
            JsonObject changed=result("changed",5000,"recall");changed.addProperty("sourceFingerprint","not-compatible");
            write(root.resolve("runs/changed-source.json"),changed);
            JsonObject legacySource=result("old-source",1500,"understanding");legacySource.addProperty("sourceFingerprint","old-fingerprint");
            write(root.resolve("runs/legacy-source.json"),legacySource);
            Files.writeString(root.resolve("runs/broken.json"),"{broken",StandardCharsets.UTF_8);
            List<QuizWorkbook> books=QuizWorkbookStore.load(folder,DOC,document());
            equal(books.stream().map(QuizWorkbook::id).toList(),List.of("second","old-source","first"),"newest first, compatible sources only, duplicates removed");
            equal(books.get(2).questions().size(),3,"newest saved snapshot wins over an older partial");
            require(Files.readString(root.resolve("runs/first.json")).contains("first"),"loading does not rewrite generated content");
            try {books.clear();throw new AssertionError("history was mutable");}catch(UnsupportedOperationException expected) {}

            Path legacyFolder=folder.resolve("legacy-only");JsonObject legacy=result(null,3000,"recall");
            write(legacyFolder.resolve("generated/quiz-v2/latest.json"),legacy);
            equal(QuizWorkbookStore.load(legacyFolder,DOC,document()).size(),1,"legacy latest-only result remains available");
        } finally {deleteTree(folder);}
    }

    private static void answerStateIsScopedAndPreservesRawText() throws Exception {
        Path folder=Files.createTempDirectory("quiz-workbook-answers-");
        try {
            QuizWorkbook book=QuizWorkbook.fromResult(result("../not-a-file-name",1000,"understanding"));
            String raw="  자기 말로 작성한 답\n다른 표현과 <기호> $x$도 그대로  ";
            Map<String,QuizWorkbook.Answer> answers=new LinkedHashMap<>();
            answers.put("q-ox",new QuizWorkbook.Answer("X",true));
            answers.put("q-word",new QuizWorkbook.Answer(raw,true));
            answers.put("q-essay",new QuizWorkbook.Answer("",true));
            answers.put("not-a-question",new QuizWorkbook.Answer("ignored",true));
            QuizWorkbookStore.saveAnswers(folder,book,answers);
            Map<String,QuizWorkbook.Answer> restored=QuizWorkbookStore.loadAnswers(folder,book);
            equal(restored.size(),3,"foreign question state is ignored");
            equal(restored.get("q-word").answer(),raw,"free written answers are not trimmed or graded");
            require(restored.get("q-word").revealed()&&restored.get("q-essay").revealed(),"model answer visibility persists, including empty essay drafts");
            equal(restored.get("q-ox"),new QuizWorkbook.Answer("X",true),"objective selection and reveal persist");
            try {restored.clear();throw new AssertionError("answers were mutable");}catch(UnsupportedOperationException expected) {}
            Path progress;
            try(var entries=Files.list(folder.resolve("generated/quiz-v2/progress"))) {
                List<Path> paths=entries.toList();equal(paths.size(),1,"one safe file without temporary leftovers");progress=paths.getFirst();
            }
            require(progress.getFileName().toString().matches("[0-9a-f]{64}\\.json"),"workbook identity cannot escape the progress directory");
            JsonObject saved=JsonParser.parseString(Files.readString(progress)).getAsJsonObject();
            require(!saved.getAsJsonObject("answers").getAsJsonObject("q-word").has("correct"),"written answers have no correctness or grade");
            QuizWorkbook another=QuizWorkbook.fromResult(result("another",1000,"understanding"));
            require(QuizWorkbookStore.loadAnswers(folder,another).isEmpty(),"another workbook cannot inherit this answer state");
            saved.addProperty("documentId","foreign-document");write(progress,saved);
            require(QuizWorkbookStore.loadAnswers(folder,book).isEmpty(),"mismatched document state is ignored");
            QuizWorkbookStore.saveAnswers(folder,book,Map.of("q-ox",new QuizWorkbook.Answer("not-an-option",true)));
            require(QuizWorkbookStore.loadAnswers(folder,book).isEmpty(),"invalid objective choices are not restored");
        } finally {deleteTree(folder);}
    }

    private static void catalogNamesAndDeletion() throws Exception {
        Path folder=Files.createTempDirectory("quiz-workbook-catalog-");
        try {
            Path root=folder.resolve("generated/quiz-v2");
            JsonObject old=result("old",1000,"practice_set"),raw=result("new",2000,"practice_set");
            write(root.resolve("runs/old.json"),old);write(root.resolve("runs/new.json"),raw);write(root.resolve("latest.json"),raw);
            QuizWorkbook legacy=QuizWorkbook.fromResult(old),first=QuizWorkbook.fromResult(raw);
            String legacyBytes=Files.readString(root.resolve("runs/old.json"));
            QuizWorkbookStore.rename(folder,legacy,QuizPanel.Theme.PRACTICE.title+" 문제집 - 1",List.of(legacy,first));
            first=QuizWorkbookStore.register(folder,first,List.of(legacy,first)).orElseThrow();
            equal(first.title(),QuizPanel.Theme.PRACTICE.title+" 문제집 - 2","existing names are skipped from one");
            String assigned=Files.readString(root.resolve("workbooks.json"));
            equal(QuizWorkbookStore.register(folder,QuizWorkbook.fromResult(raw),List.of(first)).orElseThrow().title(),first.title(),"stream snapshots reuse assigned name");
            equal(Files.readString(root.resolve("workbooks.json")),assigned,"existing assignment performs no extra catalog write");
            QuizWorkbookStore.saveAnswers(folder,first,Map.of("q-ox",new QuizWorkbook.Answer("O",true,true,false)));
            QuizWorkbookStore.rename(folder,first,"중요 복습",List.of(legacy,first));
            QuizWorkbook renamed=QuizWorkbookStore.register(folder,QuizWorkbook.fromResult(raw),List.of(first)).orElseThrow();
            equal(renamed.title(),"중요 복습","completion snapshot cannot overwrite manual rename");
            equal(QuizWorkbookStore.load(folder,DOC,document()).getFirst().title(),"중요 복습","rename survives reload");
            require(QuizWorkbookStore.loadAnswers(folder,renamed).get("q-ox").bookmarked(),"rename lost saved answers or checks");
            fail(()->{try {QuizWorkbookStore.rename(folder,legacy,"중요 복습",List.of(renamed));}catch(java.io.IOException e){throw new RuntimeException(e);}},"duplicate title");
            JsonObject nextRaw=result("third",3000,"practice_set");write(root.resolve("runs/third.json"),nextRaw);
            QuizWorkbook third=QuizWorkbookStore.register(folder,QuizWorkbook.fromResult(nextRaw),List.of(renamed,legacy)).orElseThrow();
            equal(third.title(),QuizPanel.Theme.PRACTICE.title+" 문제집 - 3","renaming never resets the issued sequence");
            QuizWorkbook recall=QuizWorkbookStore.register(folder,QuizWorkbook.fromResult(result("recall",4000,"recall")),List.of(third)).orElseThrow();
            equal(recall.title(),"암기 확인 N제 문제집 - 1","each workbook type starts at one");
            QuizWorkbookStore.delete(folder,renamed);QuizWorkbookStore.delete(folder,renamed);
            require(QuizWorkbookStore.load(folder,DOC,document()).stream().noneMatch(b->b.id().equals("new")),"latest/run copies resurrected deleted workbook");
            require(QuizWorkbookStore.register(folder,QuizWorkbook.fromResult(raw),List.of()).isEmpty(),"late stream resurrected deleted workbook");
            require(QuizWorkbookStore.load(folder,DOC,document()).stream().anyMatch(b->b.id().equals("old")),"deletion affected another workbook");
            equal(Files.readString(root.resolve("runs/old.json")),legacyBytes,"management rewrote generation source");
            var pool=java.util.concurrent.Executors.newFixedThreadPool(2);
            try {
                var a=pool.submit(()->QuizWorkbookStore.register(folder,QuizWorkbook.fromResult(result("parallel-a",5000,"practice_set")),List.of()).orElseThrow().title());
                var b=pool.submit(()->QuizWorkbookStore.register(folder,QuizWorkbook.fromResult(result("parallel-b",5001,"practice_set")),List.of()).orElseThrow().title());
                equal(Set.of(a.get(),b.get()),Set.of(QuizPanel.Theme.PRACTICE.title+" 문제집 - 4",QuizPanel.Theme.PRACTICE.title+" 문제집 - 5"),"concurrent allocation collided");
            } finally {pool.shutdownNow();}
            String good=Files.readString(root.resolve("workbooks.json"));Files.writeString(root.resolve("workbooks.json"),"{broken");
            try {QuizWorkbookStore.register(folder,third,List.of());throw new AssertionError("bad catalog was overwritten");}catch(java.io.IOException expected){}
            equal(Files.readString(root.resolve("workbooks.json")),"{broken","failed write changed catalog");Files.writeString(root.resolve("workbooks.json"),good);
            for(String invalid:List.of(" ","이름\n줄바꿈","x".repeat(121)))fail(()->QuizWorkbookStore.validTitle(invalid),"invalid name");
        } finally {deleteTree(folder);}
    }

    private static JsonObject result(String id,long created,String theme) {
        JsonObject value=new JsonObject();
        value.addProperty("kind","quiz");value.addProperty("documentId",DOC);value.addProperty("promptVersion","quiz-v2");
        value.addProperty("sourceFingerprint","current-fingerprint");if(id!=null)value.addProperty("quizRunId",id);
        value.addProperty("startedAtMs",created);value.addProperty("completedAtMs",created+500);
        value.addProperty("requestedCount",3);value.addProperty("unfilled",0);value.addProperty("reason","");value.addProperty("elapsedSeconds",11.5);
        JsonObject setup=new JsonObject();setup.addProperty("theme",theme);setup.addProperty("difficulty","중상");value.add("quiz",setup);
        JsonObject usage=new JsonObject();usage.addProperty("usageBasedUsd",.012);usage.addProperty("unknownUsageRequests",0);value.add("runUsage",usage);
        JsonArray questions=new JsonArray();
        for(String type:List.of("ox","word","essay")) {
            JsonObject q=new JsonObject();q.addProperty("id","q-"+type);q.addProperty("type",type);q.addProperty("concept","수업 개념");
            q.addProperty("stem",type+" 형식의 핵심 조건을 확인하시오.");q.addProperty("answer",type.equals("ox")?"O":"모범답안");
            q.addProperty("explanation","자료의 조건에 따른 설명이다.");q.add("options",new JsonArray());
            JsonArray points=new JsonArray();if(type.equals("essay"))points.add("핵심 조건");q.add("keyPoints",points);
            JsonObject evidence=new JsonObject();evidence.addProperty("sourceId","study:c1:e1");evidence.addProperty("page",2);
            evidence.addProperty("quote","핵심 조건에 대한 개념 정의");evidence.addProperty("sourceKind","saved_concept");
            JsonArray citations=new JsonArray();citations.add(evidence);q.add("evidence",citations);questions.add(q);
        }
        value.add("questions",questions);return value;
    }
    private static JsonObject document() {
        JsonObject value=new JsonObject();value.addProperty("fingerprint","current-fingerprint");
        JsonArray legacy=new JsonArray();legacy.add("old-fingerprint");value.add("legacySourceFingerprints",legacy);return value;
    }
    private static void write(Path file,JsonObject value) throws Exception {
        Files.createDirectories(file.getParent());Files.writeString(file,JSON.toJson(value),StandardCharsets.UTF_8);
    }
    private static void deleteTree(Path folder) throws Exception {
        try(var paths=Files.walk(folder)) {for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}
    }
    private static void fail(Runnable action,String message) {
        try {action.run();throw new AssertionError("Accepted "+message);}catch(IllegalArgumentException expected) {}
    }
    private static void equal(Object actual,Object expected,String message) {if(!Objects.equals(actual,expected))throw new AssertionError(message+": "+actual+" != "+expected);}
    private static void require(boolean condition,String message) {if(!condition)throw new AssertionError(message);}
}
