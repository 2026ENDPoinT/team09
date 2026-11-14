package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Read-only regression of the reported file, using an offline derived projection. */
public final class SourceUnitContinuityTest {
    public static void main(String[] args)throws Exception {
        JsonObject result=JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject();
        String original=result.toString();var groups=ConceptOutline.groups(result);
        var cards=SummaryOutline.objects(result,"concepts");int checked=0;
        for(int i=0;i<cards.size();i++) {
            String name=cards.get(i).get("name").getAsString();
            if(!Set.of("냉전","냉전 시기의 지정학적 대립구도").contains(name))continue;
            int at=i;var group=groups.stream().filter(g->g.concepts().contains(at)).findFirst().orElseThrow();
            check(group.path().stream().anyMatch(h->h.id().equals("h:v2p19f1")),"Cold War content returned to the chapter instead of its original unit: "+group);
            check(group.path().stream().noneMatch(h->h.id().equals("h:v2p16f2")),"A different numbered unit was merged into the preceding one");checked++;
        }
        check(checked==2,"Reported concept fixtures not found");
        var rows=ConceptOutline.displayRows(groups);
        check(rows.stream().filter(r->r.heading()&&r.title().contains("‘자유민주주의’와 ‘반공주의’ 사이 대한민국")).count()==1,
            "Chapter heading restarted in the middle of the same sequence");
        check(rows.stream().filter(r->!r.heading()).flatMap(r->r.concepts().stream()).toList()
            .equals(java.util.stream.IntStream.range(0,cards.size()).boxed().toList()),"Concept content was lost/reordered");
        check(original.equals(result.toString()),"Saved body or paid metadata changed");
        System.out.println("SourceUnitContinuityTest passed: both reported concepts share their actual numbered source unit; one chapter header, intact card order and prose");
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
