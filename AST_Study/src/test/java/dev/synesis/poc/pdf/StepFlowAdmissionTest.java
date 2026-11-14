package dev.synesis.poc.pdf;

import com.google.gson.*;
import javax.swing.*;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.LinkedHashMap;
import java.util.Map;

/** No API, PDF import, native window or user cache: saved and fresh presentation contracts. */
public final class StepFlowAdmissionTest {
    private static final JsonObject INDEX=JsonParser.parseString("{\"pages\":[{},{}]}").getAsJsonObject();

    public static void main(String[] args)throws Exception {
        validStampRequired();duplicates();distinctMathAndCodeBodies();visualEvidence();fallbackPreservesContent();markdownRemainsMarkdown();workspaceFallbacks();
        System.out.println("PASS: StepFlow policy/minimum/duplicate gates and lossless summary/concept fallback");
    }

    private static void validStampRequired() {
        for(String kind:new String[]{"process","procedure","derivation","cycle"}) {
            JsonObject block=block();block.getAsJsonObject("stepFlow").getAsJsonObject("eligibility").addProperty("kind",kind);
            check(StepFlow.resolve(block,INDEX)!=null,"approved "+kind+" rejected");
            check(StepFlow.fallbackHtml(block,INDEX,18).isEmpty(),"approved card also rendered a fallback");
        }
        for(String invalid:new String[]{"legacy","version","kind","false","string","count","fraction"}) {
            JsonObject block=block(),flow=block.getAsJsonObject("stepFlow"),stamp=flow.getAsJsonObject("eligibility");
            switch(invalid) {
                case "legacy"->flow.remove("eligibility");
                case "version"->stamp.addProperty("policyVersion","ordered-process-v1");
                case "kind"->stamp.addProperty("kind","comparison");
                case "false"->stamp.addProperty("sourceGrounded",false);
                case "string"->stamp.addProperty("sourceGrounded","true");
                case "count"->stamp.addProperty("transitionCount",3);
                case "fraction"->stamp.addProperty("transitionCount",2.1);
            }
            check(StepFlow.resolve(block,INDEX)==null,"unapproved "+invalid+" became a card");
            check(StepFlow.fallbackHtml(block,INDEX,18).contains("자료를 수집합니다."),"unapproved content hidden");
        }
        JsonObject two=block();JsonObject flow=two.getAsJsonObject("stepFlow");
        flow.getAsJsonArray("steps").remove(2);flow.getAsJsonObject("eligibility").addProperty("transitionCount",1);
        check(StepFlow.resolve(two,INDEX)==null,"two items became a card");
        check(StepFlow.fallbackHtml(two,INDEX,18).contains("<ul>"),"two items have no ordinary fallback");
    }

    private static void duplicates() {
        for(boolean title:new boolean[]{true,false})for(boolean markdown:new boolean[]{true,false}) {
            JsonObject block=block();JsonArray steps=block.getAsJsonObject("stepFlow").getAsJsonArray("steps");
            steps.get(0).getAsJsonObject().addProperty(title?"title":"body",markdown?"**1. 자료 수집**":"① 자료 수집");
            steps.get(1).getAsJsonObject().addProperty(title?"title":"body",title
                ?(markdown?"**2. 자료-수집！**":"２） 자료-수집！")
                :(markdown?"**2. 자료  수집**":"２） 자료  수집"));
            check(StepFlow.resolve(block,INDEX)==null,"normalized duplicate "+(title?"title":"body")+" admitted");
            String fallback=StepFlow.fallbackHtml(block,INDEX,18);
            check(fallback.contains("자료 수집") && (!title || fallback.contains("자료-수집！")),"duplicate fallback rewrote the source");
        }
        JsonObject numeric=block();JsonArray steps=numeric.getAsJsonObject("stepFlow").getAsJsonArray("steps");
        steps.get(0).getAsJsonObject().addProperty("body","1.0 m");
        steps.get(1).getAsJsonObject().addProperty("body","2.0 m");
        check(StepFlow.resolve(numeric,INDEX)!=null,"distinct numeric values were erased as step numbering");
    }

    private static void distinctMathAndCodeBodies() {
        for(String[] bodies:new String[][]{
                {"다음 값은 \\(x-1\\)이에요.","다음 값은 \\(x+1\\)이에요.","다음 값은 \\(x1\\)이에요."},
                {"`value = x*2;`","`value = x2;`","`Value = x2;`"},
                {"*p = x;","p = x;","p = X;"}}) {
            JsonObject block=block();JsonArray steps=block.getAsJsonObject("stepFlow").getAsJsonArray("steps");
            for(int i=0;i<bodies.length;i++)steps.get(i).getAsJsonObject().addProperty("body",bodies[i]);
            check(StepFlow.resolve(block,INDEX)!=null,"meaningful math/code sign or identifier case was erased");
        }
    }

    private static void fallbackPreservesContent() {
        JsonObject block=block(),flow=block.getAsJsonObject("stepFlow");flow.remove("eligibility");
        JsonObject first=flow.getAsJsonArray("steps").get(0).getAsJsonObject();
        first.addProperty("context","실험 맥락");first.addProperty("insight","연결 조건을 확인해요.");
        first.addProperty("body","본문의 **중요 조건**과 `x = 3`을 보존해요.");
        JsonArray refs=first.getAsJsonArray("evidence");
        refs.add(JsonParser.parseString("{\"page\":2,\"quote\":\"두 번째 근거\"}"));
        refs.add(JsonParser.parseString("{\"page\":999,\"quote\":\"페이지 확인이 필요한 근거\"}"));
        flow.getAsJsonArray("steps").get(1).getAsJsonObject().addProperty("title","<img src='remote'> 정제");
        String original=block.toString(),fallback=StepFlow.fallbackHtml(block,INDEX,18);
        for(String text:new String[]{"<ul>","실험 맥락","연결 조건을 확인해요.","중요 조건","x = 3",
                "자료 검토","두 번째 근거","페이지 확인이 필요한 근거","href='page:1'","href='page:2'"})
            check(fallback.contains(text),"fallback dropped "+text);
        check(!fallback.contains("href='page:999'") && !fallback.contains("<img src="),"fallback invented an unsafe element/link");
        check(block.toString().equals(original),"presentation mutated the saved module");
    }

    private static void visualEvidence() {
        JsonObject block=block();JsonArray steps=block.getAsJsonObject("stepFlow").getAsJsonArray("steps");
        JsonObject ref=JsonParser.parseString("""
            {"page":1,"quote":"","sourceMode":"visual","source":"region_image","bbox":[0.1,0.2,0.8,0.9]}
            """).getAsJsonObject();
        JsonArray evidence=new JsonArray();evidence.add(ref);steps.get(0).getAsJsonObject().add("evidence",evidence);
        check(StepFlow.resolve(block,INDEX)!=null,"source-grounded visual stage requires a fabricated quote");
        for(String invalid:new String[]{"sourceMode","source","emptyBox","reversed","outside","typed","page"}) {
            JsonObject changed=block.deepCopy();JsonObject bad=changed.getAsJsonObject("stepFlow").getAsJsonArray("steps").get(0).getAsJsonObject().getAsJsonArray("evidence").get(0).getAsJsonObject();
            switch(invalid) {
                case "sourceMode"->bad.remove("sourceMode");
                case "source"->bad.addProperty("source","native");
                case "emptyBox"->bad.add("bbox",new JsonArray());
                case "reversed"->bad.add("bbox",JsonParser.parseString("[0.8,0.2,0.1,0.9]"));
                case "outside"->bad.add("bbox",JsonParser.parseString("[-0.1,0.2,0.8,0.9]"));
                case "typed"->bad.add("bbox",JsonParser.parseString("[\"0.1\",0.2,0.8,0.9]"));
                case "page"->bad.addProperty("page",3);
            }
            check(StepFlow.resolve(changed,INDEX)==null,"invalid visual evidence "+invalid+" admitted");
        }
        block.getAsJsonObject("stepFlow").remove("eligibility");
        String fallback=StepFlow.fallbackHtml(block,INDEX,18);
        check(fallback.contains("시각 원문 <a href='page:1'>p.1</a>") && fallback.contains("자료를 수집합니다."),
              "legacy visual fallback lost source page or stage body");
    }

    private static void markdownRemainsMarkdown() {
        String html=StudyMarkdown.render("1. 수치형 자료\n2. 범주형 자료\n3. 순서형 자료",18);
        check(html.contains("<ol>") && !html.contains("SLIDELENS") && !html.contains("step-flow"),"ordinary Markdown became a card");
    }

    private static void workspaceFallbacks()throws Exception {
        Path temporary=Files.createTempDirectory("synesis-flow-fallback-");
        SwingUtilities.invokeAndWait(()->{
            try(PdfWorkspace workspace=new PdfWorkspace(false,temporary)) {
                Field index=PdfWorkspace.class.getDeclaredField("index");index.setAccessible(true);index.set(workspace,INDEX);
                JsonObject entry=block();entry.getAsJsonObject("stepFlow").remove("eligibility");
                entry.addProperty("title","주제");entry.addProperty("body","원래 요약 본문");
                entry.addProperty("definition","원래 개념 정의");entry.addProperty("explanation","원래 개념 설명");
                entry.add("evidence",new JsonArray());entry.add("visualPages",new JsonArray());
                String original=entry.toString();
                Method summary=PdfWorkspace.class.getDeclaredMethod("summaryBlock",JsonObject.class,String.class,boolean.class,Map.class);
                summary.setAccessible(true);
                String summaryHtml=(String)summary.invoke(workspace,entry,"fallback-summary",true,new LinkedHashMap<String,SlideLens.Request>());
                check(summaryHtml.contains("원래 요약 본문") && summaryHtml.contains("자료를 수집합니다.")
                    && summaryHtml.contains("<ul>") && !summaryHtml.contains("/step-flow"),"saved summary fallback missing/duplicated card");
                JsonObject concept=new JsonObject();concept.addProperty("name","주제");JsonArray entries=new JsonArray();entries.add(entry);concept.add("entries",entries);
                Method details=PdfWorkspace.class.getDeclaredMethod("createConceptDetails",JsonObject.class,String.class,int.class);
                details.setAccessible(true);Container panel=(Container)details.invoke(workspace,concept,"fallback-concept",18);
                String text=allText(panel);
                check(text.contains("원래 개념 설명") && text.contains("자료를 수집합니다.")
                    && text.contains("모은 자료의 오류를 정제합니다.") && text.contains("수집한 자료를 검토합니다."),"saved concept fallback hid a step");
                check(!hasCard(panel),"saved concept fallback still used a card");
                check(entry.toString().equals(original),"workspace changed saved data");
                entry.add("stepFlow",StepFlowTest.fixtureModule());
                String approved=(String)summary.invoke(workspace,entry,"approved-summary",true,new LinkedHashMap<String,SlideLens.Request>());
                check(approved.contains("approved-summary/step-flow") && !approved.contains("자료를 수집합니다."),"approved summary lost its card or duplicated fallback");
                Container approvedConcept=(Container)details.invoke(workspace,concept,"approved-concept",18);
                check(hasCard(approvedConcept),"approved concept lost its card");
            } catch(Exception failure) {throw new RuntimeException(failure);}
        });
    }

    private static JsonObject block(){JsonObject block=new JsonObject();block.add("stepFlow",StepFlowTest.fixtureModule());return block;}
    private static String allText(Container parent)throws Exception {
        StringBuilder text=new StringBuilder();
        for(Component child:parent.getComponents()) {
            if(child instanceof JEditorPane pane)text.append(pane.getDocument().getText(0,pane.getDocument().getLength()));
            else if(child instanceof Container nested)text.append(allText(nested));
        }
        return text.toString();
    }
    private static boolean hasCard(Container parent) {
        for(Component child:parent.getComponents())if(child instanceof StepFlow.Panel || child instanceof Container nested && hasCard(nested))return true;
        return false;
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
