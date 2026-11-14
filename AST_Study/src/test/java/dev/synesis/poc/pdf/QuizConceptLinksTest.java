package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.nio.file.*;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.*;

/** Local metadata, reveal and navigation contracts; no app, provider or user data. */
public final class QuizConceptLinksTest {
    private static final String DOC="concept-link-fixture";
    public static void main(String[] args)throws Exception {
        metadataAndLegacyResolution();
        changedConceptsAndDocuments();
        currentAndPreviousWorkbooksRetainLinks();
        SwingUtilities.invokeAndWait(()->{
            tagsAreLazyAndFollowRevealState();
            panelRejectsStaleNavigation();
            destinationOpensOnlyOneConcept();
        });
        System.out.println("QuizConceptLinksTest passed: saved IDs/legacy metadata, reordered and stale concepts, lazy tags, reveal state, document guards and one-card local navigation. No paid calls.");
        System.exit(0);
    }
    private static void metadataAndLegacyResolution() {
        JsonObject raw=result();
        QuizQuestion parsed=QuizGenerationData.parse(raw,DOC).questions().getFirst();
        equal(parsed.conceptIds(),List.of("c1","c2"),"wire IDs survive parsing");
        try {parsed.conceptIds().clear();throw new AssertionError("IDs mutable");}catch(UnsupportedOperationException expected){}
        equal(QuizConceptLinks.resolve(parsed,study("개념 A","개념 B")).stream().map(QuizConceptLinks.Target::index).toList(),List.of(0,1),"multiple concepts link independently");
        raw.getAsJsonArray("questions").get(0).getAsJsonObject().remove("conceptIds");
        QuizQuestion legacy=QuizGenerationData.parse(raw,DOC).questions().getFirst();
        equal(QuizConceptLinks.resolve(legacy,study("개념 A","개념 B")).size(),2,"old saved titles/evidence need no regeneration");
        JsonArray invalid=new JsonArray();invalid.add(JsonNull.INSTANCE);invalid.add(true);invalid.add("invalid");
        raw.getAsJsonArray("questions").get(0).getAsJsonObject().add("conceptIds",invalid);
        equal(QuizGenerationData.parse(raw,DOC).questions().size(),1,"damaged optional navigation does not discard a question");
        equal(QuizConceptLinks.resolve(question("개념 · A",List.of()),study("개념 · A")).size(),1,"a title's middle dot is not split unnecessarily");
    }
    private static void changedConceptsAndDocuments() {
        QuizQuestion q=question("개념 A",List.of("c1"));
        var first=QuizConceptLinks.resolve(q,study("개념 A","개념 B")).getFirst();
        JsonObject reordered=study("개념 B","개념 A");
        equal(QuizConceptLinks.resolve(q,reordered).getFirst().index(),1,"positional ID cannot override a saved name");
        equal(QuizConceptLinks.find(first,reordered),1,"a queued target can follow an unchanged concept after reordering");
        equal(QuizConceptLinks.find(first,study("개념 C","개념 B")),-1,"replaced concept is not opened");
        JsonObject foreign=study("개념 A");foreign.addProperty("documentId","other");
        equal(QuizConceptLinks.resolve(q,foreign),List.of(),"other PDF has no tags");
        equal(QuizConceptLinks.find(first,foreign),-1,"other PDF cannot receive a queued click");
        equal(QuizConceptLinks.resolve(question("개념 A",List.of()),study("개념 A","개념 A")),List.of(),"ambiguous legacy titles do not guess");
        equal(QuizConceptLinks.resolve(q,null),List.of(),"missing concept tab needs no request");
    }
    private static void currentAndPreviousWorkbooksRetainLinks()throws Exception {
        Path folder=Files.createTempDirectory("quiz-concept-history-");
        try {
            Path runs=folder.resolve("generated/quiz-v2/runs");Files.createDirectories(runs);
            int index=0;
            for(String version:List.of("quiz-v2","quiz-v3.3-quality","quiz-v3.4-direct-completion")) {
                JsonObject raw=result();raw.addProperty("promptVersion",version);raw.addProperty("sourceFingerprint","fp");
                raw.addProperty("quizRunId","run-"+index);raw.addProperty("startedAtMs",++index);
                Files.writeString(runs.resolve(index+".json"),raw.toString());
            }
            JsonObject document=new JsonObject();document.addProperty("fingerprint","fp");
            List<QuizWorkbook> books=QuizWorkbookStore.load(folder,DOC,document);
            equal(books.size(),3,"current and historical workbooks reopen without paid regeneration");
            for(var book:books)equal(QuizConceptLinks.resolve(book.questions().getFirst(),study("개념 A","개념 B")).size(),2,
                "saved workbook retains concept IDs for local links");
        } finally {
            try(var files=Files.walk(folder)){for(Path p:files.sorted(java.util.Comparator.reverseOrder()).toList())Files.delete(p);}
        }
    }
    private static void tagsAreLazyAndFollowRevealState() {
        QuizQuestion q=question("개념 A · 개념 B",List.of("c1","c2"));
        AtomicInteger resolved=new AtomicInteger();List<QuizConceptLinks.Target> clicked=new ArrayList<>();
        QuizQuestionCard card=new QuizQuestionCard(q,ignored->{});
        card.setConceptNavigation(()->{resolved.incrementAndGet();return QuizConceptLinks.resolve(q,study("개념 A","개념 B"));},clicked::add);
        equal(resolved.get(),0,"unrevealed cards do no concept work");
        equal(tags(card).size(),0,"concepts must not leak an answer");
        card.choiceButtons.get("O").doClick();card.checkButton.doClick();
        equal(resolved.get(),1,"concepts resolve when revealed");
        List<JButton> tags=tags(card);equal(tags.size(),2,"one tag per related concept");
        tags.get(1).doClick();equal(clicked.getFirst().title(),"개념 B","each tag opens its own concept");
        String answer=card.userAnswer();
        card.choiceButtons.get("X").doClick();tags.getFirst().doClick();
        equal(clicked.size(),1,"hidden stale tags cannot navigate");
        card.restore(new QuizWorkbook.Answer(answer,true));
        equal(tags(card).size(),2,"restoring revealed answers restores tags");
        equal(card.userAnswer(),answer,"navigation metadata does not change answers");
    }
    private static void panelRejectsStaleNavigation() {
        QuizPanel panel=new QuizPanel();panel.reset(3,DOC);panel.setReady(true);
        List<QuizConceptLinks.Target> opened=new ArrayList<>();
        panel.setConceptNavigation(q->QuizConceptLinks.resolve(q,study("개념 A")),opened::add);
        panel.showQuestions(List.of(question("개념 A",List.of("c1"))));
        QuizQuestionCard card=panel.cards.getFirst();card.choiceButtons.get("O").doClick();card.checkButton.doClick();
        JButton tag=tags(card).getFirst();tag.doClick();equal(opened.size(),1,"panel forwards the local target");
        panel.reset(2,"other");tag.doClick();equal(opened.size(),1,"old question cannot navigate a new document");
    }
    private static void destinationOpensOnlyOneConcept() {
        JPanel list=new JPanel();list.setLayout(new BoxLayout(list,BoxLayout.Y_AXIS));
        JScrollPane scroll=new JScrollPane(list);
        ConceptOverview overview=new ConceptOverview(list,scroll,new JSlider(10,24,16),new JComboBox<>(new String[]{"전체"}),new JButton());
        AtomicInteger first=new AtomicInteger(),second=new AtomicInteger();
        ConceptOverview.Card a=new ConceptOverview.Card("a",overview,false,ignored->{},ignored->{});
        ConceptOverview.Card b=new ConceptOverview.Card("b",overview,false,ignored->{},ignored->{});
        a.update("개념 A",List.of(),"a",()->{first.incrementAndGet();return new JLabel("A 본문");});
        b.update("개념 B",List.of(),"b",()->{second.incrementAndGet();return new JLabel("B 본문");});
        overview.showCards("fixture",List.of(a,b),"");overview.search.setText("개념 A");
        require(overview.revealConcept(1),"target must be available");
        equal(overview.search.getText(),"","search cannot hide the destination");
        equal(first.get(),0,"other cards remain lazy");equal(second.get(),1,"only target content is built");
        overview.revealConcept(1);equal(second.get(),1,"repeat navigation reuses target content");
        require(!overview.revealConcept(3),"invalid index must not navigate");overview.dispose();
    }
    private static List<JButton> tags(Component root) {
        List<JButton> result=new ArrayList<>();
        if(root instanceof JButton button&&button.getName()!=null&&button.getName().startsWith("quiz-concept:"))result.add(button);
        if(root instanceof Container container)for(Component child:container.getComponents())result.addAll(tags(child));
        return result;
    }
    private static QuizQuestion question(String title,List<String> ids) {
        return new QuizQuestion("q",DOC,QuizQuestion.Type.OX,title,"조건에 맞는가?",List.of(),"O","해설",List.of(),
            List.of(new QuizQuestion.Evidence("native",1,"근거")),false,ids);
    }
    private static JsonObject study(String... names) {
        JsonObject result=new JsonObject();result.addProperty("documentId",DOC);JsonArray concepts=new JsonArray();
        for(String name:names){JsonObject concept=new JsonObject();concept.addProperty("name",name);concept.addProperty("definition",name+"의 정의");concepts.add(concept);}
        result.add("concepts",concepts);return result;
    }
    private static JsonObject result() {
        return JsonParser.parseString("""
            {"documentId":"concept-link-fixture","requestedCount":1,"unfilled":0,"elapsedSeconds":1,
             "questions":[{"id":"q","type":"ox","concept":"개념 A · 개념 B","conceptIds":["c1","c2"],
             "stem":"조건에 맞는가?","options":[],"answer":"O","explanation":"해설","keyPoints":[],
             "evidence":[{"sourceId":"study:c1:e1","page":1,"quote":"근거","sourceKind":"saved_concept"}]}]}
            """).getAsJsonObject();
    }
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    private static void equal(Object actual,Object expected,String message){if(!Objects.equals(actual,expected))throw new AssertionError(message+": "+actual+" != "+expected);}
}
