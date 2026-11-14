package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.text.Normalizer;
import java.util.*;

/** Generated runs stay immutable; a small local catalog holds names and deletion markers. */
final class QuizWorkbookStore {
    private static final Gson JSON=new GsonBuilder().disableHtmlEscaping().create();
    private static final String PROGRESS_FORMAT="quiz-workbook-progress";
    private record Candidate(QuizWorkbook workbook,long completedAtMs,long modifiedAtMs) {}
    private QuizWorkbookStore() {}

    static List<QuizWorkbook> load(Path folder,String documentId,JsonObject document) {
        Map<String,Candidate> books=new HashMap<>();
        Path generated=folder.resolve("generated/quiz-v2");
        Path runs=generated.resolve("runs");
        if(Files.isDirectory(runs))try(var entries=Files.newDirectoryStream(runs,"*.json")) {
            for(Path path:entries)readCandidate(path,documentId,document,books);
        } catch(IOException ignored) { /* The legacy latest set can still be opened. */ }
        readCandidate(generated.resolve("latest.json"),documentId,document,books);
        JsonObject catalog;
        try {catalog=readCatalog(folder,documentId);}
        catch(IOException invalid) {catalog=newCatalog(documentId);}
        JsonObject entries=catalog.getAsJsonObject("entries");
        return books.values().stream().map(Candidate::workbook)
            .filter(book->!deleted(entries,book.id()))
            .map(book->named(book,entries))
            .sorted(Comparator.comparingLong(QuizWorkbook::createdAtMs).reversed().thenComparing(QuizWorkbook::id))
            .toList();
    }

    private static void readCandidate(Path path,String documentId,JsonObject document,Map<String,Candidate> books) {
        if(!Files.isRegularFile(path))return;
        try {
            JsonObject value=JsonParser.parseString(Files.readString(path,StandardCharsets.UTF_8)).getAsJsonObject();
            String version=text(value,"promptVersion");
            if(!documentId.equals(text(value,"documentId"))||!("quiz-v2".equals(version)||version.startsWith("quiz-v3.")||version.startsWith("quiz-v4"))
                    ||!compatibleFingerprint(value,document))return;
            QuizWorkbook workbook=QuizWorkbook.fromResult(value);
            Candidate candidate=new Candidate(workbook,positiveLong(value,"completedAtMs"),Files.getLastModifiedTime(path).toMillis());
            Candidate old=books.get(workbook.id());
            if(old==null||newer(candidate,old))books.put(workbook.id(),candidate);
        } catch(IOException|RuntimeException ignored) { /* A damaged/empty run does not hide other workbooks. */ }
    }

    private static boolean newer(Candidate candidate,Candidate previous) {
        int completed=Long.compare(candidate.completedAtMs(),previous.completedAtMs());
        if(completed!=0)return completed>0;
        int questionCount=Integer.compare(candidate.workbook().questions().size(),previous.workbook().questions().size());
        if(questionCount!=0)return questionCount>0;
        return candidate.modifiedAtMs()>previous.modifiedAtMs();
    }

    private static boolean compatibleFingerprint(JsonObject value,JsonObject document) {
        if(document==null)return false;
        String fingerprint=text(value,"sourceFingerprint");
        if(fingerprint.equals(text(document,"fingerprint")))return true;
        if(document.has("legacySourceFingerprints")&&document.get("legacySourceFingerprints").isJsonArray())
            for(JsonElement old:document.getAsJsonArray("legacySourceFingerprints"))
                if(old.isJsonPrimitive()&&old.getAsJsonPrimitive().isString()&&fingerprint.equals(old.getAsString()))return true;
        return false;
    }

    static synchronized Optional<QuizWorkbook> register(Path folder,QuizWorkbook book,Collection<QuizWorkbook> known) throws IOException {
        JsonObject catalog=readCatalog(folder,book.documentId()),entries=catalog.getAsJsonObject("entries");
        if(deleted(entries,book.id()))return Optional.empty();
        if(entries.has(book.id())&&!text(entries.getAsJsonObject(book.id()),"title").isBlank())return Optional.of(named(book,entries));
        Set<String> used=titles(entries,known,book.documentId(),book.id());
        JsonObject counters=catalog.getAsJsonObject("nextNumbers");
        long number=Math.max(1,positiveLong(counters,book.theme().name()));
        String title;
        do {
            if(number==Long.MAX_VALUE)throw new IOException("문제집 번호를 배정할 수 없어요.");
            title=book.theme().title+" 문제집 - "+number++;
        } while(used.contains(normalizeTitle(title)));
        JsonObject entry=new JsonObject();entry.addProperty("title",title);entry.addProperty("deleted",false);entries.add(book.id(),entry);
        counters.addProperty(book.theme().name(),number);writeAtomic(catalogPath(folder),catalog);
        return Optional.of(book.withTitle(title));
    }

    static synchronized String rename(Path folder,QuizWorkbook book,String requested,Collection<QuizWorkbook> known) throws IOException {
        String title=validTitle(requested);
        JsonObject catalog=readCatalog(folder,book.documentId()),entries=catalog.getAsJsonObject("entries");
        if(deleted(entries,book.id()))throw new IllegalArgumentException("이미 삭제된 문제집이에요.");
        if(titles(entries,known,book.documentId(),book.id()).contains(normalizeTitle(title)))
            throw new IllegalArgumentException("같은 이름의 문제집이 있어요. 다른 이름을 입력해 주세요.");
        JsonObject entry=new JsonObject();entry.addProperty("title",title);entry.addProperty("deleted",false);entries.add(book.id(),entry);
        writeAtomic(catalogPath(folder),catalog);return title;
    }

    static synchronized void delete(Path folder,QuizWorkbook book) throws IOException {
        JsonObject catalog=readCatalog(folder,book.documentId()),entries=catalog.getAsJsonObject("entries");
        JsonObject entry=new JsonObject();entry.addProperty("title",named(book,entries).title());entry.addProperty("deleted",true);entries.add(book.id(),entry);
        // A marker also hides legacy latest/request copies and later snapshots of an active run.
        writeAtomic(catalogPath(folder),catalog);
    }

    static String validTitle(String requested) {
        String title=requested==null?"":Normalizer.normalize(requested,Normalizer.Form.NFC).strip();
        if(title.isBlank()||title.length()>120||title.codePoints().anyMatch(Character::isISOControl))
            throw new IllegalArgumentException("문제집 이름을 1–120자로 입력해 주세요. 줄바꿈은 사용할 수 없어요.");
        return title;
    }
    private static String normalizeTitle(String title) {return Normalizer.normalize(title,Normalizer.Form.NFKC).strip().toLowerCase(Locale.ROOT);}
    private static Set<String> titles(JsonObject entries,Collection<QuizWorkbook> known,String documentId,String exceptId) {
        Set<String> result=new HashSet<>();
        for(var entry:entries.entrySet())if(!entry.getKey().equals(exceptId)&&entry.getValue().isJsonObject()&&!deleted(entries,entry.getKey()))
            result.add(normalizeTitle(text(entry.getValue().getAsJsonObject(),"title")));
        for(QuizWorkbook book:known)if(book.documentId().equals(documentId)&&!book.id().equals(exceptId)&&!deleted(entries,book.id()))
            result.add(normalizeTitle(named(book,entries).title()));
        return result;
    }
    private static QuizWorkbook named(QuizWorkbook book,JsonObject entries) {
        JsonElement entry=entries.get(book.id());String title=entry!=null&&entry.isJsonObject()?text(entry.getAsJsonObject(),"title"):"";
        return title.isBlank()?book:book.withTitle(title);
    }
    private static boolean deleted(JsonObject entries,String id) {return entries.has(id)&&entries.get(id).isJsonObject()&&flag(entries.getAsJsonObject(id),"deleted");}
    private static Path catalogPath(Path folder) {return folder.resolve("generated/quiz-v2/workbooks.json");}
    private static JsonObject newCatalog(String documentId) {
        JsonObject value=new JsonObject();value.addProperty("format","quiz-workbook-catalog");value.addProperty("version",1);value.addProperty("documentId",documentId);
        value.add("entries",new JsonObject());value.add("nextNumbers",new JsonObject());return value;
    }
    private static JsonObject readCatalog(Path folder,String documentId) throws IOException {
        Path path=catalogPath(folder);if(!Files.exists(path))return newCatalog(documentId);
        try {
            JsonObject value=JsonParser.parseString(Files.readString(path,StandardCharsets.UTF_8)).getAsJsonObject();
            if(!"quiz-workbook-catalog".equals(text(value,"format"))||positiveLong(value,"version")!=1||!documentId.equals(text(value,"documentId"))
                ||!value.has("entries")||!value.get("entries").isJsonObject()||!value.has("nextNumbers")||!value.get("nextNumbers").isJsonObject())
                throw new IOException("문제집 목록의 저장 정보를 확인할 수 없어요.");
            return value;
        } catch(RuntimeException invalid){throw new IOException("문제집 목록의 저장 정보를 읽지 못했어요.",invalid);}
    }

    static Map<String,QuizWorkbook.Answer> loadAnswers(Path folder,QuizWorkbook book) {
        Path path=progressPath(folder,book);
        if(!Files.isRegularFile(path))return Map.of();
        try {
            JsonObject value=JsonParser.parseString(Files.readString(path,StandardCharsets.UTF_8)).getAsJsonObject();
            if(!PROGRESS_FORMAT.equals(text(value,"format"))||positiveLong(value,"version")!=1
                    ||!book.documentId().equals(text(value,"documentId"))||!book.id().equals(text(value,"workbookId"))
                    ||!value.has("answers")||!value.get("answers").isJsonObject())return Map.of();
            JsonObject saved=value.getAsJsonObject("answers");
            Map<String,QuizWorkbook.Answer> answers=new LinkedHashMap<>();
            for(QuizQuestion question:book.questions()) {
                JsonElement item=saved.get(question.id());
                if(item==null||!item.isJsonObject())continue;
                JsonObject answer=item.getAsJsonObject();
                if(!answer.has("answer")||!answer.get("answer").isJsonPrimitive()
                        ||!answer.getAsJsonPrimitive("answer").isString()
                        ||!answer.has("revealed")||!answer.get("revealed").isJsonPrimitive()
                        ||!answer.getAsJsonPrimitive("revealed").isBoolean())continue;
                QuizWorkbook.Answer normalized=validAnswer(question,new QuizWorkbook.Answer(answer.get("answer").getAsString(),answer.get("revealed").getAsBoolean(),flag(answer,"bookmarked"),flag(answer,"skipped")));
                if(normalized!=null)answers.put(question.id(),normalized);
            }
            return Collections.unmodifiableMap(answers);
        } catch(IOException|RuntimeException ignored) {return Map.of();}
    }

    static synchronized void saveAnswers(Path folder,QuizWorkbook book,Map<String,QuizWorkbook.Answer> values) throws IOException {
        Objects.requireNonNull(values);
        JsonObject state=new JsonObject();
        state.addProperty("format",PROGRESS_FORMAT);state.addProperty("version",1);
        state.addProperty("documentId",book.documentId());state.addProperty("workbookId",book.id());
        state.addProperty("updatedAtMs",System.currentTimeMillis());
        JsonObject answers=new JsonObject();
        for(QuizQuestion question:book.questions()) {
            QuizWorkbook.Answer answer=values.get(question.id());
            if(answer==null)continue;
            answer=validAnswer(question,answer);if(answer==null)continue;
            JsonObject item=new JsonObject();item.addProperty("answer",answer.answer());item.addProperty("revealed",answer.revealed());
            item.addProperty("bookmarked",answer.bookmarked());item.addProperty("skipped",answer.skipped());
            answers.add(question.id(),item);
        }
        state.add("answers",answers);
        writeAtomic(progressPath(folder,book),state);
    }

    private static void writeAtomic(Path target,JsonObject state) throws IOException {
        Files.createDirectories(target.getParent());
        Path temporary=Files.createTempFile(target.getParent(),"answers-",".tmp");
        try {
            Files.writeString(temporary,JSON.toJson(state),StandardCharsets.UTF_8);
            try {Files.move(temporary,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
            catch(AtomicMoveNotSupportedException unsupported) {Files.move(temporary,target,StandardCopyOption.REPLACE_EXISTING);}
        } finally {Files.deleteIfExists(temporary);}
    }

    private static QuizWorkbook.Answer validAnswer(QuizQuestion question,QuizWorkbook.Answer answer) {
        if(question.selfComparison())return answer;
        if(answer.answer().isEmpty())return new QuizWorkbook.Answer("",answer.revealed()&&answer.skipped(),answer.bookmarked(),answer.revealed()&&answer.skipped());
        boolean valid=question.type()==QuizQuestion.Type.OX?Set.of("O","X").contains(answer.answer())
            :question.options().stream().anyMatch(option->option.id().equals(answer.answer()));
        return valid?answer:null;
    }

    private static boolean flag(JsonObject value,String key) {
        JsonElement field=value.get(key);
        return field!=null&&field.isJsonPrimitive()&&field.getAsJsonPrimitive().isBoolean()&&field.getAsBoolean();
    }

    private static Path progressPath(Path folder,QuizWorkbook book) {
        String identity=book.documentId()+"\u0000"+book.id();
        try {
            String name=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(identity.getBytes(StandardCharsets.UTF_8)));
            return folder.resolve("generated/quiz-v2/progress").resolve(name+".json");
        } catch(NoSuchAlgorithmException impossible) {throw new IllegalStateException(impossible);}
    }
    private static String text(JsonObject value,String key) {
        JsonElement field=value.get(key);
        return field!=null&&field.isJsonPrimitive()&&field.getAsJsonPrimitive().isString()?field.getAsString():"";
    }
    private static long positiveLong(JsonObject value,String key) {
        try {
            JsonElement field=value.get(key);
            return field!=null&&field.isJsonPrimitive()&&field.getAsJsonPrimitive().isNumber()
                ?Math.max(0,field.getAsBigDecimal().longValueExact()):0;
        } catch(ArithmeticException invalid){return 0;}
    }
}
