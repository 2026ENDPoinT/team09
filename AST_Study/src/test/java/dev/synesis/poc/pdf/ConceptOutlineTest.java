package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Offline full-document membership checks plus ambiguous/cross-chapter cases. */
public final class ConceptOutlineTest {
    public static void main(String[] args)throws Exception {
        localGroupingContracts();
        selectiveSubsections();
        List<String> report=new ArrayList<>();
        for(String name:List.of("finance","sequences","anatomy","integration")) {
            JsonObject result=JsonParser.parseString(Files.readString(Path.of("build/hierarchy-cleanup-20261018-014638",name,"result.json"))).getAsJsonObject();
            String before=result.toString();var groups=ConceptOutline.groups(result);
            check(!groups.isEmpty(),"No source groups for "+name);
            List<Integer> indices=groups.stream().flatMap(g->g.concepts().stream()).toList();
            check(indices.size()==result.getAsJsonArray("concepts").size(),"Missing concepts: "+name);
            check(new HashSet<>(indices).size()==indices.size(),"Duplicated concepts: "+name);
            for(int i=0;i<indices.size();i++)check(indices.get(i)==i,"Global concept order changed: "+name);
            for(var group:groups)check(group.concepts().equals(group.concepts().stream().sorted().toList()),"Source occurrence order changed within group");
            check(before.equals(result.toString()),"Mutated original content");
            if(name.equals("finance"))check(groups.stream().map(ConceptOutline.Group::title).toList().equals(List.of(
                "6.1. 손익계산서","6.2. 재무상태표(대차대조표)","6.3. 주요 수익성 척도","6.4. 주요 주가 관련 비율")),"Finance categories differ: "+groups);
            report.add(name+": "+groups.stream().map(g->g.title()+" ["+g.concepts().size()+"]").toList());
            // A merged concept keeps its later explanations but is listed once
            // under its first grounded occurrence, without mutating its entries.
            JsonObject merged=result.deepCopy();JsonArray all=merged.getAsJsonArray("concepts");
            all.get(0).getAsJsonObject().getAsJsonArray("entries").addAll(all.get(all.size()-1).getAsJsonObject().getAsJsonArray("entries"));
            check(ConceptOutline.groups(merged).stream().filter(g->g.concepts().contains(0)).count()==1,"Merged concept duplicated");
            check(ConceptOutline.groups(merged).stream().filter(g->g.concepts().contains(0)).findFirst().orElseThrow().id().equals(groups.stream().filter(g->g.concepts().contains(0)).findFirst().orElseThrow().id()),"Later mention stole representative group");
            JsonObject unknown=result.deepCopy();JsonObject extra=new JsonObject();extra.addProperty("name","Unmatched concept");
            JsonArray entries=new JsonArray();JsonObject entry=new JsonObject();JsonArray evidence=new JsonArray();JsonObject ref=new JsonObject();ref.addProperty("sourceId","not-a-real-source");ref.addProperty("page",1);evidence.add(ref);entry.add("evidence",evidence);entries.add(entry);extra.add("entries",entries);unknown.getAsJsonArray("concepts").add(extra);
            var fallback=ConceptOutline.groups(unknown);check(fallback.getLast().id().equals("unplaced"),"Guessed category from page number");
            JsonObject legacy=result.deepCopy();legacy.remove("hierarchy");check(ConceptOutline.groups(legacy).isEmpty(),"Legacy must keep original flat order");
        }
        Files.createDirectories(Path.of("build/concept-hierarchy-check"));Files.write(Path.of("build/concept-hierarchy-check/groups.txt"),report);
        report.forEach(System.out::println);
        javax.swing.SwingUtilities.invokeAndWait(ConceptOutlineTest::filterGroups);
        ConceptOverviewTest.main(new String[]{"build/concept-hierarchy-check/finance"});
    }
    private static void localGroupingContracts() {
        JsonObject result=JsonParser.parseString("""
            {"hierarchy":{"nodes":[
              {"id":"a","parentId":"","title":"첫 단원","sourceHeading":true},
              {"id":"b","parentId":"","title":"다음 단원","sourceHeading":true}]},
             "sections":[{"parts":[
              {"nodeId":"a","title":"첫 개념","evidence":[{"sourceId":"shared"}]},
              {"nodeId":"b","title":"다음 개념","evidence":[{"sourceId":"shared"}]},
              {"nodeId":"a","title":"첫 단원 재참조","evidence":[{"sourceId":"later"}]}]}],
             "concepts":[
              {"name":"첫 개념","evidence":[{"sourceId":"shared"}]},
              {"name":"다음 개념","evidence":[{"sourceId":"shared"}]},
              {"name":"첫 단원 재참조","evidence":[{"sourceId":"later"}]}]}
            """).getAsJsonObject();
        String original=result.toString();var groups=ConceptOutline.groups(result);
        check(groups.stream().map(ConceptOutline.Group::title).toList().equals(List.of("첫 단원","다음 단원","첫 단원")),
            "Exact source/name match or closed-branch order lost: "+groups);
        check(groups.stream().flatMap(g->g.concepts().stream()).toList().equals(List.of(0,1,2)),"Later reference moved forward");
        check(groups.get(0).id().equals("a")&&!groups.get(2).id().equals("a"),"Repeated group reused UI identity");
        check(result.toString().equals(original),"Changed saved evidence");
        for(JsonObject node:SummaryOutline.objects(result.getAsJsonObject("hierarchy"),"nodes"))node.addProperty("sourceHeading",false);
        check(ConceptOutline.groups(result).stream().map(ConceptOutline.Group::title).toList().equals(groups.stream().map(ConceptOutline.Group::title).toList()),
            "Existing generated sections ignored when source typography is unavailable");
    }
    private static void selectiveSubsections() {
        JsonObject result=new JsonObject(),hierarchy=new JsonObject();JsonArray nodes=new JsonArray(),parts=new JsonArray(),concepts=new JsonArray();
        result.add("hierarchy",hierarchy);hierarchy.add("nodes",nodes);result.add("concepts",concepts);
        JsonObject section=new JsonObject();section.add("parts",parts);JsonArray sections=new JsonArray();sections.add(section);result.add("sections",sections);
        for(String id:List.of("root","a","b","c","d","e","f")) {
            JsonObject node=new JsonObject();node.addProperty("id",id);node.addProperty("title",id);node.addProperty("parentId",id.equals("root")?"":"root");node.addProperty("sourceHeading",true);nodes.add(node);
        }
        // Singleton slides used to veto useful groups a/b. Scattered c returns
        // must remain under root, with no guessing from their neighbours.
        List<String> owners=List.of("a","a","c","b","b","d","c","e","f");
        for(int i=0;i<owners.size();i++) {
            JsonObject ref=new JsonObject();ref.addProperty("sourceId","ref"+i);JsonArray evidence=new JsonArray();evidence.add(ref);
            JsonObject part=new JsonObject();part.addProperty("nodeId",owners.get(i));part.addProperty("title","concept"+i);part.add("evidence",evidence);parts.add(part);
            JsonObject concept=new JsonObject();concept.addProperty("name","concept"+i);concept.add("evidence",evidence.deepCopy());concepts.add(concept);
        }
        String original=result.toString();var groups=ConceptOutline.groups(result);
        check(groups.stream().map(ConceptOutline.Group::title).toList().equals(List.of("a","root","b","root")),"Selective subsection split failed: "+groups);
        check(groups.stream().flatMap(g->g.concepts().stream()).toList().equals(java.util.stream.IntStream.range(0,owners.size()).boxed().toList()),"Selective split reordered concepts");
        check(original.equals(result.toString()),"Selective split changed content");
        parts.get(4).getAsJsonObject().addProperty("nodeId","d");
        parts.get(5).getAsJsonObject().addProperty("nodeId","b");
        check(ConceptOutline.groups(result).size()==1,"One useful subsection should not fragment the chapter");
    }
    private static void filterGroups() {
        javax.swing.JPanel list=new javax.swing.JPanel();list.setLayout(new javax.swing.BoxLayout(list,javax.swing.BoxLayout.Y_AXIS));
        javax.swing.JScrollPane scroll=new javax.swing.JScrollPane(list);
        ConceptOverview overview=new ConceptOverview(list,scroll,new javax.swing.JSlider(6,64,16),new javax.swing.JComboBox<>(new String[]{"전체 자료"}),new javax.swing.JButton());
        try {
            var first=new ConceptOverview.Card("a",overview,false,open->{},page->{});
            var second=new ConceptOverview.Card("b",overview,false,open->{},page->{});
            first.update("첫 개념",List.of(1),"a",()->{throw new AssertionError("Closed card rendered body");});
            second.update("다음 개념",List.of(2),"b",()->{throw new AssertionError("Closed card rendered body");});
            overview.showCards("doc",List.of(first,second),"안내",List.of(new ConceptOutline.Group("one","첫 단원",List.of(0)),new ConceptOutline.Group("two","다음 단원",List.of(1))));
            check(list.getComponent(1).getName().equals("concept-group:첫 단원")&&list.getComponent(2)==first,"Group/card order incorrect");
            overview.search.setText("다음");
            var filter=ConceptOverview.class.getDeclaredMethod("filter");filter.setAccessible(true);filter.invoke(overview);
            check(!list.getComponent(1).isVisible()&&!first.isVisible(),"Empty group survived search");
            check(list.getComponent(3).isVisible()&&second.isVisible(),"Matching group hidden");
            overview.search.setText("");filter.invoke(overview);
            check(list.getComponent(1).isVisible()&&first.isVisible(),"Clearing search did not restore groups");
        }catch(ReflectiveOperationException error){throw new RuntimeException(error);}finally {overview.dispose();}
    }
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
}
