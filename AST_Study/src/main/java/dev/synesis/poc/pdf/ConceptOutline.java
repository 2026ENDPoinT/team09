package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.*;

/** Read-only concept placement using existing hierarchy and exact source evidence. */
final class ConceptOutline {
    record Heading(String id,String title) {}
    record Group(String id,String title,List<Integer> concepts,List<Heading> path) {
        Group(String id,String title,List<Integer> concepts) {this(id,title,concepts,List.of(new Heading(id,title)));}
    }
    /** Headings carry filter/count membership; only content rows contain cards. */
    record DisplayRow(String id,boolean heading,int depth,String number,String title,boolean continuation,List<Integer> concepts) {}
    private record Grounding(String owner,String title,Set<String> refs) {}
    private ConceptOutline() {}

    static List<Group> groups(JsonObject result) {
        List<JsonObject> concepts=SummaryOutline.objects(result,"concepts");
        if(result==null||!result.has("hierarchy")||!result.get("hierarchy").isJsonObject())return List.of();
        List<JsonObject> nodes=SummaryOutline.objects(result.getAsJsonObject("hierarchy"),"nodes");
        Map<String,JsonObject> known=new LinkedHashMap<>();
        for(JsonObject node:nodes)known.put(text(node,"id"),node);
        List<String> roots=nodes.stream().filter(n->text(n,"parentId").isEmpty()).map(n->text(n,"id")).toList();
        if(roots.isEmpty())return List.of();
        List<Grounding> grounding=new ArrayList<>();
        // Use original owners, not UI occurrence/continuation IDs. Repeated
        // source references in the summary must not strand a merged concept.
        for(JsonObject section:SummaryOutline.objects(result,"sections")) {
            List<JsonObject> parts=SummaryOutline.objects(section,"parts");
            for(JsonObject part:parts.isEmpty()?List.of(section):parts) {
                String owner=text(part,"nodeId");
                if(known.containsKey(owner))grounding.add(new Grounding(owner,text(part,"title"),refs(part)));
            }
        }
        Set<String> categories=new LinkedHashSet<>(roots);
        if(Set.of("study-hierarchy-k1.1","study-hierarchy-k1.11","study-hierarchy-k1.1.1").contains(text(result.getAsJsonObject("hierarchy"),"version"))) {
            // Shared plan ancestry is structural; card density must not erase it.
            for(JsonObject node:nodes)if(text(node,"sourceKind").equals("planned_topic"))
                categories.add(text(node,"id"));
        } else {
            if(text(result.getAsJsonObject("hierarchy"),"version").equals("study-hierarchy-7"))
                preserveNumberedPaths(nodes,concepts,grounding,known,categories);
            preserveSourceBranches(nodes,concepts,grounding,known,categories);
            List<String> initial=place(concepts,grounding,known,categories);
            for(String root:roots) {
                List<String> children=nodes.stream().filter(n->source(n)&&text(n,"parentId").equals(root)
                    &&!text(n,"sourceKind").equals("classification")).map(n->text(n,"id")).toList();
                long size=initial.stream().filter(root::equals).count();
                // Keep small chapters shallow. Expand large chapters only when
                // multiple real subsections have actual concept members.
                int threshold=text(known.get(root),"sourceKind").equals("numbered")?12:24;
                if(children.size()<2||roots.size()>1&&size<threshold)continue;
                Set<String> trial=new LinkedHashSet<>(categories);trial.addAll(children);
                List<String> placements=place(concepts,grounding,known,trial);
                long supported=children.stream().filter(c->placements.stream().filter(c::equals).count()>=2).count();
                long shown=placements.stream().filter(c->c.equals(root)||children.contains(c)).distinct().count();
                // Preserve established, reasonably dense chapter subdivisions,
                // including a small number of useful one-concept subsections.
                if(supported>=2&&size>=shown*2) {
                    categories.addAll(children);continue;
                }
                // Select useful subsections independently. Sparse slide headings
                // must not veto every populated subsection in the entire chapter.
                // Require a consecutive pair: scattered returns are not a reason
                // to create a separate heading above several singleton cards.
                Set<String> populated=new LinkedHashSet<>();
                for(int i=1;i<placements.size();i++) {
                    String id=placements.get(i);
                    if(id.equals(placements.get(i-1))&&children.contains(id))populated.add(id);
                }
                // Sparse children stay under their existing parent; never absorb
                // them into a neighbouring subsection or change concept order.
                if(populated.size()>=2)categories.addAll(populated);
            }
        }
        List<String> placements=place(concepts,grounding,known,categories);
        Map<String,List<Integer>> members=new LinkedHashMap<>();
        Map<String,String> owners=new LinkedHashMap<>();String previous="",run="";
        for(int i=0;i<placements.size();i++) {
            String id=placements.get(i);if(id.isEmpty())id="unplaced";
            if(!id.equals(previous)) {
                run=members.containsKey(id)?id+"/occurrence/"+i:id;
                members.put(run,new ArrayList<>());owners.put(run,id);previous=id;
            }
            members.get(run).add(i);
        }
        if(members.isEmpty()||owners.values().stream().allMatch("unplaced"::equals))return List.of();
        List<Group> groups=new ArrayList<>();
        // Keep exact existing concept order. Returning to a parent after its
        // children gets another display occurrence, never a move above them.
        for(var entry:members.entrySet()) {
            String owner=owners.get(entry.getKey());
            String title=owner.equals("unplaced")?"기타 개념":text(known.get(owner),"title");
            List<Heading> path=new ArrayList<>();String cursor=owner;Set<String> seen=new HashSet<>();
            while(known.containsKey(cursor)&&seen.add(cursor)) {
                if(categories.contains(cursor))path.add(new Heading(cursor,text(known.get(cursor),"title")));
                cursor=text(known.get(cursor),"parentId");
            }
            Collections.reverse(path);
            if(path.isEmpty())path.add(new Heading(owner,title));
            groups.add(new Group(entry.getKey(),title,List.copyOf(entry.getValue()),List.copyOf(path)));
        }
        return List.copyOf(groups);
    }

    private static void preserveNumberedPaths(List<JsonObject> nodes,List<JsonObject> concepts,
            List<Grounding> grounding,Map<String,JsonObject> known,Set<String> categories) {
        Map<String,List<String>> siblings=new LinkedHashMap<>();
        for(JsonObject child:nodes) {
            String parentId=text(child,"parentId");JsonObject parent=known.get(parentId);
            if(source(child)&&source(parent)&&text(child,"structuralRole").equals("numbered_heading")
                    &&structuralChild(child,parent))
                siblings.computeIfAbsent(parentId,k->new ArrayList<>()).add(text(child,"id"));
        }
        for(var entry:siblings.entrySet()) {
            if(entry.getValue().size()<2)continue;
            List<String> path=new ArrayList<>();Set<String> seen=new HashSet<>();String cursor=entry.getKey();
            while(!cursor.isEmpty()) {
                JsonObject node=known.get(cursor);
                if(!source(node)||!seen.add(cursor)){path.clear();break;}
                path.add(cursor);cursor=text(node,"parentId");
            }
            if(path.isEmpty())continue;
            Set<String> trial=new LinkedHashSet<>(categories);trial.addAll(path);trial.addAll(entry.getValue());
            Set<String> populated=new LinkedHashSet<>(place(concepts,grounding,known,trial));
            populated.retainAll(entry.getValue());
            // Only h7's explicit local numbered roles can open an otherwise
            // sparse intermediate branch, and two children must be grounded.
            if(populated.size()>=2){categories.addAll(path);categories.addAll(populated);}
        }
    }

    private static void preserveSourceBranches(List<JsonObject> nodes,List<JsonObject> concepts,
            List<Grounding> grounding,Map<String,JsonObject> known,Set<String> categories) {
        // A small slide can explicitly contain several source subsections with
        // one concept each. Their grounded source structure is stronger evidence
        // than the card-count heuristic used for sparse, unrelated slide titles.
        // A later-page typography heading with its own explicit subsections
        // is a real branch too. Do not flatten it merely because its chapter
        // started on an earlier page; isolated slide titles stay shallow.
        Set<String> branchedTitles=new HashSet<>();
        for(JsonObject node:nodes)if(source(node)&&text(node,"sourceKind").equals("title")
                &&!text(node,"startBlockId").isEmpty()&&!text(node,"endBlockId").isEmpty()
                &&nodes.stream().filter(child->source(child)&&text(child,"parentId").equals(text(node,"id"))
                    &&structuralChild(child,node)).count()>=2)branchedTitles.add(text(node,"id"));
        for(String id:branchedTitles) {
            JsonObject branch=known.get(id);
            List<String> children=nodes.stream().filter(child->source(child)&&text(child,"parentId").equals(id)
                &&structuralChild(child,branch)).map(child->text(child,"id")).toList();
            List<String> path=new ArrayList<>();Set<String> seen=new HashSet<>();String cursor=id;
            while(!cursor.isEmpty()) {
                JsonObject node=known.get(cursor);
                if(!source(node)||!seen.add(cursor)){path.clear();break;}
                path.add(cursor);cursor=text(node,"parentId");
            }
            if(path.isEmpty())continue;
            Set<String> trial=new LinkedHashSet<>(categories);trial.addAll(path);trial.addAll(children);
            Set<String> populated=new LinkedHashSet<>(place(concepts,grounding,known,trial));populated.retainAll(children);
            if(populated.size()>=2){categories.addAll(path);categories.addAll(populated);}
        }
        boolean changed;
        do {
            changed=false;
            for(JsonObject parent:nodes) {
                String parentId=text(parent,"id");
                if(!source(parent)||!categories.contains(parentId))continue;
                List<String> children=nodes.stream().filter(child->source(child)
                    &&text(child,"parentId").equals(parentId)
                    &&(structuralChild(child,parent)||branchedTitles.contains(text(child,"id"))))
                    .map(child->text(child,"id")).toList();
                if(children.size()<2)continue;
                Set<String> trial=new LinkedHashSet<>(categories);trial.addAll(children);
                Set<String> populated=new LinkedHashSet<>(place(concepts,grounding,known,trial));
                populated.retainAll(children);
                if(populated.size()>=2)changed|=categories.addAll(populated);
            }
        } while(changed);
    }

    private static boolean structuralChild(JsonObject child,JsonObject parent) {
        String kind=text(child,"sourceKind");
        if(kind.equals("classification")||text(child,"startBlockId").isEmpty()
                ||text(child,"endBlockId").isEmpty())return false;
        // Explicit numbering/markers may span pages. Unnumbered typography is
        // accepted here only within its parent's source page; ordinary sparse
        // slide titles retain the existing density-based presentation policy.
        return Set.of("numbered","marked","list").contains(kind)
            ||kind.equals("title")&&!text(child,"page").isEmpty()
                &&text(child,"page").equals(text(parent,"page"));
    }

    static List<DisplayRow> displayRows(List<Group> groups) {
        Map<String,List<Integer>> scopes=new LinkedHashMap<>();
        for(Group group:groups)for(Heading heading:group.path())
            scopes.computeIfAbsent(heading.id(),k->new ArrayList<>()).addAll(group.concepts());
        Map<String,String> numbers=new LinkedHashMap<>();Map<String,Integer> counts=new HashMap<>();
        List<DisplayRow> rows=new ArrayList<>();List<Heading> previous=List.of();
        for(Group group:groups) {
            List<Heading> path=group.path();int shared=0;
            while(shared<previous.size()&&shared<path.size()&&previous.get(shared).id().equals(path.get(shared).id()))shared++;
            // Returning to an ancestor explicitly closes the preceding child.
            // Its title is not a new chapter and must not be numbered again.
            int start=shared==path.size()&&previous.size()>path.size()?path.size()-1:shared;
            for(int i=start;i<path.size();i++) {
                Heading heading=path.get(i);String parent=i==0?"":path.get(i-1).id();
                boolean continued=numbers.containsKey(heading.id());
                if(!continued) {
                    int number=counts.merge(parent,1,Integer::sum);
                    numbers.put(heading.id(),i==0?String.format("%02d",number):numbers.get(parent)+"."+number);
                }
                rows.add(new DisplayRow(continued?"resume:"+group.id()+":"+heading.id():"heading:"+heading.id(),true,i,
                    numbers.get(heading.id()),heading.title(),continued,
                    List.copyOf(continued?group.concepts():scopes.get(heading.id()))));
            }
            rows.add(new DisplayRow("cards:"+group.id(),false,Math.max(0,path.size()-1),"","",false,group.concepts()));
            previous=path;
        }
        return List.copyOf(rows);
    }
    private static List<String> place(List<JsonObject> concepts,List<Grounding> grounding,Map<String,JsonObject> known,Set<String> categories) {
        Map<String,Set<String>> evidence=new HashMap<>();
        Map<String,List<Grounding>> named=new HashMap<>();
        for(Grounding item:grounding) {
            String category=nearest(item.owner(),known,categories);if(category.isEmpty())continue;
            for(String ref:item.refs())evidence.computeIfAbsent(ref,k->new LinkedHashSet<>()).add(category);
            named.computeIfAbsent(item.title(),k->new ArrayList<>()).add(item);
        }
        List<String> placed=new ArrayList<>();
        for(JsonObject concept:concepts) {
            List<JsonObject> entries=SummaryOutline.objects(concept,"entries");if(entries.isEmpty())entries=List.of(concept);
            String category="";
            // Preserve a cross-chapter concept intact under its first grounded
            // entry. All later explanations remain inside the same card.
            for(JsonObject entry:entries) {
                Set<String> references=refs(entry);Set<String> exact=new LinkedHashSet<>();
                for(Grounding item:named.getOrDefault(text(entry,"name"),List.of()))
                    if(!references.isEmpty()&&references.equals(item.refs()))exact.add(nearest(item.owner(),known,categories));
                if(exact.size()==1){category=exact.iterator().next();break;}
                Map<String,Integer> scores=new LinkedHashMap<>();
                for(String ref:references)for(String candidate:evidence.getOrDefault(ref,Set.of()))scores.merge(candidate,1,Integer::sum);
                if(scores.isEmpty())continue;
                int best=Collections.max(scores.values());
                List<String> matches=scores.entrySet().stream().filter(e->e.getValue()==best).map(Map.Entry::getKey).toList();
                category=matches.size()==1?matches.getFirst():common(matches,known,categories);break;
            }
            placed.add(category);
        }
        return placed;
    }
    private static String nearest(String id,Map<String,JsonObject> nodes,Set<String> categories) {
        Set<String> seen=new HashSet<>();
        while(nodes.containsKey(id)&&seen.add(id)) {
            if(categories.contains(id))return id;id=text(nodes.get(id),"parentId");
        }
        return "";
    }
    private static String common(List<String> ids,Map<String,JsonObject> nodes,Set<String> categories) {
        List<List<String>> paths=new ArrayList<>();
        for(String id:ids) {
            List<String> path=new ArrayList<>();Set<String> seen=new HashSet<>();
            while(nodes.containsKey(id)&&seen.add(id)){path.add(id);id=text(nodes.get(id),"parentId");}
            paths.add(path);
        }
        for(String candidate:paths.getFirst())if(categories.contains(candidate)&&paths.stream().allMatch(p->p.contains(candidate)))return candidate;
        return "";
    }
    private static Set<String> refs(JsonObject value) {
        Set<String> out=new LinkedHashSet<>();
        for(JsonObject ref:SummaryOutline.objects(value,"evidence"))if(!text(ref,"sourceId").isEmpty())out.add(text(ref,"sourceId"));
        return out;
    }
    private static boolean source(JsonObject node) {return node!=null&&node.has("sourceHeading")&&node.get("sourceHeading").isJsonPrimitive()&&node.get("sourceHeading").getAsBoolean();}
    private static String text(JsonObject value,String key) {return value!=null&&value.has(key)&&value.get(key).isJsonPrimitive()?value.get(key).getAsString():"";}
}
