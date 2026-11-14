package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Headless read-only audit of locally upgraded saved results, including all scopes. */
public final class SavedHierarchyCorpusAudit {
    public static void main(String[] args)throws Exception {
        JsonArray rows=new JsonArray();int conceptsChecked=0,partsChecked=0;
        try(var paths=Files.walk(Path.of(args[0]))) {
            for(Path path:paths.filter(p->p.toString().endsWith(".json")).sorted().toList()) {
                JsonObject result;
                try {result=JsonParser.parseString(Files.readString(path)).getAsJsonObject();}
                catch(RuntimeException bad) {continue;}
                if(!result.has("sections")||!result.has("hierarchy"))continue;
                String before=result.toString();var groups=ConceptOutline.groups(result);
                int count=SummaryOutline.objects(result,"concepts").size();
                List<Integer> placed=groups.stream().flatMap(g->g.concepts().stream()).toList();
                if(count>0) {
                    check(placed.size()==count,"Lost/duplicated concept cards",path);
                    for(int i=0;i<count;i++)check(placed.get(i)==i,"Reordered concept cards",path);
                }
                var entries=SummaryOutline.entries(result);int parts=0;
                Set<String> ids=new HashSet<>();
                for(var entry:entries)for(JsonObject part:entry.content()) {
                    parts++;String id=part.has("contentId")?part.get("contentId").getAsString():"";
                    check(id.isEmpty()||ids.add(id),"Duplicated summary content",path);
                }
                int expected=0;
                for(JsonObject section:SummaryOutline.objects(result,"sections")) {
                    var list=SummaryOutline.objects(section,"parts");expected+=list.isEmpty()?1:list.size();
                }
                check(parts==expected,"Lost summary explanation",path);
                check(before.equals(result.toString()),"Mutated saved body/evidence/usage",path);
                JsonObject row=new JsonObject();row.addProperty("file",path.toString());
                row.addProperty("concepts",count);row.addProperty("summaryParts",parts);
                row.addProperty("groups",groups.size());
                row.addProperty("unplacedConcepts",groups.stream().filter(g->g.id().startsWith("unplaced"))
                    .mapToInt(g->g.concepts().size()).sum());
                row.addProperty("maxConceptDepth",groups.stream().mapToInt(g->g.path().size()).max().orElse(0));
                JsonArray structure=new JsonArray();
                for(var group:groups) {
                    JsonObject g=new JsonObject();g.addProperty("title",group.title());
                    JsonArray trail=new JsonArray();group.path().forEach(h->trail.add(h.title()));g.add("path",trail);
                    g.addProperty("members",group.concepts().size());structure.add(g);
                }
                row.add("structure",structure);rows.add(row);conceptsChecked+=count;partsChecked+=parts;
            }
        }
        JsonObject report=new JsonObject();report.addProperty("savedResults",rows.size());
        report.addProperty("conceptsChecked",conceptsChecked);report.addProperty("summaryPartsChecked",partsChecked);
        report.add("results",rows);Files.writeString(Path.of(args[1]),new GsonBuilder().setPrettyPrinting().create().toJson(report));
        System.out.println("Saved hierarchy audit passed: "+rows.size()+" results, "+conceptsChecked+" concepts, "+partsChecked+" explanations");
    }
    private static void check(boolean ok,String message,Path path) {
        if(!ok)throw new AssertionError(message+": "+path);
    }
}
