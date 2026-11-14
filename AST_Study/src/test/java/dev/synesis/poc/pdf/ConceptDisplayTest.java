package dev.synesis.poc.pdf;

import com.google.gson.*;
import javax.swing.*;
import java.awt.*;
import java.util.*;
import java.util.List;

/** Local presentation contracts; no PDF regeneration, network, or judge. */
public final class ConceptDisplayTest {
    private static final ConceptOutline.Heading ROOT=new ConceptOutline.Heading("r","공통 단원");
    private static final ConceptOutline.Heading CHILD=new ConceptOutline.Heading("c","소단원");
    static List<ConceptOutline.Group> fixture() {
        return List.of(new ConceptOutline.Group("r","공통 단원",List.of(0),List.of(ROOT)),
            new ConceptOutline.Group("c","소단원",List.of(1,2),List.of(ROOT,CHILD)),
            new ConceptOutline.Group("r/occurrence/3","공통 단원",List.of(3),List.of(ROOT)));
    }
    public static void main(String[] args)throws Exception {
        var rows=ConceptOutline.displayRows(fixture());
        check(rows.stream().filter(r->r.heading()&&!r.continuation()&&r.title().equals("공통 단원")).count()==1,"Parent repeated");
        check(rows.stream().filter(r->!r.heading()).flatMap(r->r.concepts().stream()).toList().equals(List.of(0,1,2,3)),"Cards reordered");
        check(rows.get(0).concepts().equals(List.of(0,1,2,3)),"Parent count/filter excludes children");
        var resume=rows.get(4);check(resume.heading()&&resume.continuation()&&resume.depth()==0&&resume.number().equals("01"),"Parent return unmarked");
        var childOnly=ConceptOutline.displayRows(List.of(fixture().get(1)));
        check(childOnly.size()==3&&childOnly.get(0).title().equals("공통 단원")&&childOnly.get(1).number().equals("01.1"),"Parent without direct content lost");
        var sameTitle=new ConceptOutline.Heading("other","공통 단원");
        var homonyms=ConceptOutline.displayRows(List.of(fixture().getFirst(),new ConceptOutline.Group("other","공통 단원",List.of(1),List.of(sameTitle))));
        check(homonyms.stream().filter(r->r.heading()&&!r.continuation()).count()==2,"Same title merged distinct source IDs");
        check(ConceptOutline.displayRows(List.of()).isEmpty(),"Legacy empty groups changed");
        sourceBranchContracts();
        laterPageBranchContracts();
        numberedIntermediateContracts();
        sourceUnitSequenceContracts();
        SwingUtilities.invokeAndWait(ConceptDisplayTest::ui);
        System.out.println("ConceptDisplayTest passed: single parent, child scope, return boundary, exact card order, homonyms, filtering, indentation and cached bodies");
    }

    private static void sourceUnitSequenceContracts() {
        var first=new ConceptOutline.Heading("first-unit","첫 원문 단위");
        var next=new ConceptOutline.Heading("next-unit","다음 원문 단위");
        var third=new ConceptOutline.Heading("third-unit","마지막 원문 단위");
        var groups=List.of(new ConceptOutline.Group("first-unit",first.title(),List.of(0),List.of(ROOT,first)),
            new ConceptOutline.Group("next-unit",next.title(),List.of(1),List.of(ROOT,next)),
            new ConceptOutline.Group("detail",CHILD.title(),List.of(2),List.of(ROOT,next,CHILD)),
            new ConceptOutline.Group("third-unit",third.title(),List.of(3),List.of(ROOT,third)));
        var rows=ConceptOutline.displayRows(groups);
        check(rows.stream().filter(r->r.heading()&&r.depth()==0).count()==1,"Same continuous chapter was restarted between source units");
        check(rows.stream().noneMatch(ConceptOutline.DisplayRow::continuation),"Source-unit transition was rendered as a parent return");
        check(rows.stream().filter(r->r.heading()&&r.depth()==1).map(ConceptOutline.DisplayRow::number).toList()
            .equals(List.of("01.1","01.2","01.3")),"Unit numbering was reset");
        check(rows.stream().filter(r->!r.heading()).flatMap(r->r.concepts().stream()).toList().equals(List.of(0,1,2,3)),"Continuity moved concept cards");
    }

    private static void laterPageBranchContracts() {
        JsonObject result=sourceBranches();
        var nodes=result.getAsJsonObject("hierarchy").getAsJsonArray("nodes");
        // Move the explicit child group to the next page underneath a named
        // source title, rather than leaving its concepts under a chapter return.
        JsonObject branch=sourceNode("later","root","Source discussion","title",2);nodes.add(branch);
        for(JsonElement element:nodes) {
            JsonObject node=element.getAsJsonObject();
            if(text(node,"parentId").equals("root")&&!text(node,"id").equals("later")) {
                node.addProperty("parentId","later");node.addProperty("page",2);
            }
        }
        String before=result.toString();var groups=ConceptOutline.groups(result);
        check(groups.getFirst().path().stream().anyMatch(h->h.id().equals("later")),"A later-page source branch with explicit children was flattened");
        check(groups.getFirst().path().size()==3,"Later source title lost its proven subsections");
        check(groups.stream().flatMap(g->g.concepts().stream()).toList().equals(List.of(0,1,2,3)),"Later branch changed concept order");
        check(before.equals(result.toString()),"Later branch changed saved content");
    }

    private static void numberedIntermediateContracts() {
        JsonObject result=numberedIntermediate();String original=result.toString();
        var groups=ConceptOutline.groups(result);
        check(groups.stream().map(ConceptOutline.Group::title).toList().equals(List.of("1) 절대적 이동","2) 상대적 이동","다음 단원")),
            "Grounded numbered siblings under an unexpanded intermediate parent were flattened: "+groups);
        check(groups.subList(0,2).stream().allMatch(g->g.path().size()==3&&g.path().stream().map(ConceptOutline.Heading::id).toList()
            .subList(0,2).equals(List.of("root","middle"))),"Numbered siblings lost their source ancestor path");
        check(groups.stream().flatMap(g->g.concepts().stream()).toList().equals(List.of(0,1,2)),"Numbered branch promotion reordered saved concepts");
        var rows=ConceptOutline.displayRows(groups);
        check(rows.stream().filter(r->r.heading()&&r.depth()==2).map(ConceptOutline.DisplayRow::number).toList()
            .equals(List.of("01.1.1","01.1.2")),"Numbered child display paths differ");
        check(result.toString().equals(original),"Numbered branch grouping changed saved prose or paid metadata");

        JsonObject legacy=result.deepCopy();legacy.getAsJsonObject("hierarchy").addProperty("version","study-hierarchy-6");
        check(ConceptOutline.groups(legacy).getFirst().path().size()==1,"h7 numbered roles changed legacy h6 sparse policy");
        JsonObject missingRole=result.deepCopy();
        SummaryOutline.objects(missingRole.getAsJsonObject("hierarchy"),"nodes").stream().filter(n->text(n,"id").equals("relative"))
            .forEach(n->n.remove("structuralRole"));
        check(ConceptOutline.groups(missingRole).getFirst().path().size()==1,"One numbered role opened a sparse intermediate branch");
        JsonObject ungrounded=result.deepCopy();ungrounded.getAsJsonArray("concepts").get(1).getAsJsonObject()
            .add("evidence",JsonParser.parseString("[{\"sourceId\":\"unknown\"}]"));
        check(ConceptOutline.groups(ungrounded).getFirst().path().size()==1,"Ungrounded sibling opened a numbered branch");
        JsonObject generated=result.deepCopy();
        SummaryOutline.objects(generated.getAsJsonObject("hierarchy"),"nodes").stream().filter(n->text(n,"id").equals("middle"))
            .forEach(n->n.addProperty("sourceHeading",false));
        check(ConceptOutline.groups(generated).getFirst().path().size()==1,"Generated wrapper was promoted as a source ancestor");
    }

    private static JsonObject numberedIntermediate() {
        JsonObject result=new JsonObject(),hierarchy=new JsonObject(),section=new JsonObject();
        JsonArray nodes=new JsonArray(),parts=new JsonArray(),concepts=new JsonArray(),sections=new JsonArray();
        hierarchy.addProperty("version","study-hierarchy-7");hierarchy.add("nodes",nodes);result.add("hierarchy",hierarchy);
        result.add("concepts",concepts);section.add("parts",parts);sections.add(section);result.add("sections",sections);
        nodes.add(sourceNode("root","","교육과 사회 이동","numbered",1));
        nodes.add(sourceNode("middle","root","이동의 구분","marked",1));
        nodes.add(sourceNode("other","","다음 단원","numbered",3));
        String[] ids={"absolute","relative","other"},titles={"1) 절대적 이동","2) 상대적 이동","다음 단원"};
        for(int i=0;i<ids.length;i++) {
            if(i<2) {
                JsonObject node=sourceNode(ids[i],"middle",titles[i],"list",i+1);
                node.addProperty("structuralRole","numbered_heading");nodes.add(node);
            }
            JsonArray evidence=new JsonArray();JsonObject ref=new JsonObject();ref.addProperty("sourceId","numbered-ref"+i);evidence.add(ref);
            JsonObject part=new JsonObject();part.addProperty("nodeId",ids[i]);part.addProperty("title",titles[i]);part.addProperty("body","원래 설명 "+i);part.add("evidence",evidence);parts.add(part);
            JsonObject concept=new JsonObject();concept.addProperty("name",titles[i]);concept.add("evidence",evidence.deepCopy());concepts.add(concept);
        }
        return result;
    }

    private static void sourceBranchContracts() {
        JsonObject result=sourceBranches();String before=result.toString();
        var groups=ConceptOutline.groups(result);
        check(groups.stream().map(ConceptOutline.Group::title).toList().equals(List.of("산술적 합","객관적 사실","보편적 사회","다음 단원")),
            "Singleton source siblings were flattened: "+groups);
        check(groups.subList(0,3).stream().allMatch(g->g.path().size()==2&&g.path().getFirst().id().equals("root")),
            "Source siblings lost their shared parent");
        var rows=ConceptOutline.displayRows(groups);
        check(rows.stream().filter(r->r.heading()&&r.depth()==1).map(ConceptOutline.DisplayRow::number).toList()
            .equals(List.of("01.1","01.2","01.3")),"Source sibling numbering differs");
        check(groups.stream().flatMap(g->g.concepts().stream()).toList().equals(List.of(0,1,2,3)),"Source branches reordered cards");
        check(before.equals(result.toString()),"Source branch grouping mutated cached prose or evidence");

        JsonObject fontOnly=result.deepCopy();
        for(JsonObject node:SummaryOutline.objects(fontOnly.getAsJsonObject("hierarchy"),"nodes"))
            if(text(node,"parentId").equals("root"))node.addProperty("sourceKind","title");
        check(ConceptOutline.groups(fontOnly).getFirst().path().size()==2,"Same-page source typography was flattened");
        for(JsonObject node:SummaryOutline.objects(fontOnly.getAsJsonObject("hierarchy"),"nodes"))
            if(text(node,"parentId").equals("root"))node.addProperty("page",9);
        check(ConceptOutline.groups(fontOnly).getFirst().path().size()==1,"Sparse font-only later slides were over-split");

        JsonObject generated=result.deepCopy();
        for(JsonObject node:SummaryOutline.objects(generated.getAsJsonObject("hierarchy"),"nodes"))
            if(text(node,"parentId").equals("root"))node.addProperty("sourceHeading",false);
        check(ConceptOutline.groups(generated).getFirst().path().size()==1,"Generated leaves became source subsections");
        JsonObject ungrounded=result.deepCopy();
        for(int i=1;i<=2;i++)ungrounded.getAsJsonArray("concepts").get(i).getAsJsonObject()
            .add("evidence",JsonParser.parseString("[{\"sourceId\":\"unknown\"}]"));
        var sparse=ConceptOutline.groups(ungrounded);
        check(sparse.getFirst().path().size()==1,"A lone grounded subsection fragmented a small chapter");
        check(sparse.stream().filter(g->g.id().equals("unplaced")).flatMap(g->g.concepts().stream()).toList().equals(List.of(1,2)),
            "Ungrounded cards were guessed into a source subsection");

        JsonObject nested=result.deepCopy();
        JsonObject hierarchy=nested.getAsJsonObject("hierarchy");
        hierarchy.getAsJsonArray("nodes").add(sourceNode("detailA","arithmetic","첫 세부","marked",8));
        hierarchy.getAsJsonArray("nodes").add(sourceNode("detailB","arithmetic","둘째 세부","marked",8));
        JsonArray parts=nested.getAsJsonArray("sections").get(0).getAsJsonObject().getAsJsonArray("parts");
        parts.get(0).getAsJsonObject().addProperty("nodeId","detailA");
        JsonObject extra=parts.get(0).getAsJsonObject().deepCopy();extra.addProperty("nodeId","detailB");extra.addProperty("title","추가 세부");
        extra.add("evidence",JsonParser.parseString("[{\"sourceId\":\"extra\"}]"));parts.add(extra);
        JsonObject card=new JsonObject();card.addProperty("name","추가 세부");card.add("evidence",extra.getAsJsonArray("evidence").deepCopy());
        nested.getAsJsonArray("concepts").add(card);
        var nestedGroups=ConceptOutline.groups(nested);
        check(nestedGroups.getFirst().path().size()==3&&nestedGroups.getFirst().path().get(1).id().equals("arithmetic"),
            "Nested grounded source structure was flattened");
        check(nestedGroups.stream().flatMap(g->g.concepts().stream()).toList().equals(List.of(0,1,2,3,4)),"Nested source promotion reordered cards");
    }

    private static JsonObject sourceBranches() {
        JsonObject result=new JsonObject(),hierarchy=new JsonObject(),section=new JsonObject();
        JsonArray nodes=new JsonArray(),parts=new JsonArray(),concepts=new JsonArray(),sections=new JsonArray();
        hierarchy.add("nodes",nodes);result.add("hierarchy",hierarchy);result.add("concepts",concepts);section.add("parts",parts);sections.add(section);result.add("sections",sections);
        nodes.add(sourceNode("root","","인간학적 상수로서의 사회","numbered",8));
        nodes.add(sourceNode("other","","다음 단원","numbered",9));
        String[] ids={"arithmetic","fact","universal","other"},titles={"산술적 합","객관적 사실","보편적 사회","다음 단원"};
        for(int i=0;i<ids.length;i++) {
            if(i<3)nodes.add(sourceNode(ids[i],"root",titles[i],"marked",8));
            JsonArray evidence=new JsonArray();JsonObject ref=new JsonObject();ref.addProperty("sourceId","ref"+i);evidence.add(ref);
            JsonObject part=new JsonObject();part.addProperty("nodeId",ids[i]);part.addProperty("title",titles[i]);part.addProperty("body","저장된 설명 "+i);part.add("evidence",evidence);parts.add(part);
            JsonObject concept=new JsonObject();concept.addProperty("name",titles[i]);concept.add("evidence",evidence.deepCopy());concepts.add(concept);
        }
        return result;
    }
    private static JsonObject sourceNode(String id,String parent,String title,String kind,int page) {
        JsonObject node=new JsonObject();node.addProperty("id",id);node.addProperty("parentId",parent);node.addProperty("title",title);
        node.addProperty("sourceHeading",true);node.addProperty("sourceKind",kind);node.addProperty("page",page);
        node.addProperty("startBlockId",id+"-start");node.addProperty("endBlockId",id+"-end");return node;
    }
    private static String text(JsonObject value,String key) {return value.has(key)?value.get(key).getAsString():"";}
    static void ui() {
        JPanel list=new JPanel();list.setLayout(new BoxLayout(list,BoxLayout.Y_AXIS));
        var scroll=new JScrollPane(list);var overview=new ConceptOverview(list,scroll,new JSlider(6,64,16),new JComboBox<>(new String[]{"전체 자료"}),new JButton());
        try {
            List<ConceptOverview.Card> cards=new ArrayList<>();
            for(int i=0;i<4;i++){var card=new ConceptOverview.Card("card"+i,overview,false,v->{},p->{});card.update("개념"+i,List.of(1),"same",()->{throw new AssertionError("Closed body rendered");});cards.add(card);}
            overview.showCards("doc",cards,"",fixture());
            check(cards.get(1).getInsets().left==16&&cards.get(3).getInsets().left==0,"Return still visually nested under child");
            check(list.getComponent(6).getName().equals("concept-resume:공통 단원"),"No visible resume boundary before direct parent card");
            var parent=list.getComponent(1);var child=list.getComponent(3);var resume=list.getComponent(6);
            check(((JPanel)resume).getBorder() instanceof javax.swing.border.EmptyBorder,"Parent return still draws a separator line");
            check(headerTitle(resume).contains("공통 단원")&&!headerTitle(resume).contains("이어서"),"Return hides its actual owner behind a generic continuation label");
            overview.search.setText("개념2");filter(overview);
            check(parent.isVisible()&&child.isVisible()&&!resume.isVisible(),"Search loses parent or shows empty return");
            overview.search.setText("개념3");filter(overview);
            check(parent.isVisible()&&!child.isVisible()&&resume.isVisible(),"Search makes returning content look like child");
            check(headerTitle(resume).contains("공통 단원"),"Filtered return loses chapter context");
            overview.search.setText("missing");filter(overview);
            check(!parent.isVisible()&&!child.isVisible()&&!resume.isVisible(),"Empty headings visible");
            overview.search.setText("");filter(overview);
            Component[] before=list.getComponents();overview.showCards("doc",cards,"",fixture());
            check(Arrays.equals(before,list.getComponents()),"Identical refresh rebuilt rows");
        } finally {overview.dispose();}
    }
    static String headerTitle(Component component) {
        return ((JLabel)((BorderLayout)((JPanel)component).getLayout()).getLayoutComponent(BorderLayout.CENTER)).getText();
    }
    static void filter(ConceptOverview overview) {
        try{var method=ConceptOverview.class.getDeclaredMethod("filter");method.setAccessible(true);method.invoke(overview);}catch(ReflectiveOperationException e){throw new RuntimeException(e);}
    }
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
