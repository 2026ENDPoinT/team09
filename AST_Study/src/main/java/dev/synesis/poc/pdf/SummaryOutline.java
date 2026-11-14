package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.util.*;
import java.util.List;
import javax.swing.*;
import javax.swing.text.html.*;

/** One canonical ordering for study headings, body placement and the local TOC. */
final class SummaryOutline {
    record Entry(String id,String parentId,String title,int level,int page,int endPage,List<JsonObject> content) {}
    record Target(JEditorPane pane,int offset) {}
    private SummaryOutline() {}

    static List<Entry> entries(JsonObject result) {
        if(result==null)return List.of();
        List<JsonObject> sections=objects(result,"sections");
        return build(sections,result.has("hierarchy")?objects(result.getAsJsonObject("hierarchy"),"nodes"):List.of());
    }

    static List<Entry> live(Collection<JsonObject> sections) {
        LinkedHashMap<String,JsonObject> nodes=new LinkedHashMap<>();
        for(JsonObject section:sections)if(section.has("hierarchy"))
            for(JsonObject node:objects(section.getAsJsonObject("hierarchy"),"nodes"))nodes.putIfAbsent(text(node,"id"),node);
        return build(new ArrayList<>(sections),new ArrayList<>(nodes.values()));
    }

    private static List<Entry> build(List<JsonObject> sections,List<JsonObject> nodes) {
        if(nodes.isEmpty())return legacy(sections);
        Map<String,JsonObject> known=new LinkedHashMap<>();
        for(JsonObject node:nodes)if(!text(node,"id").isBlank())known.putIfAbsent(text(node,"id"),node);
        List<Entry> out=new ArrayList<>(),open=new ArrayList<>();List<String> openBase=new ArrayList<>();
        Set<String> used=new HashSet<>(),seenContent=new HashSet<>(),parents=new HashSet<>();
        int occurrence=0;
        for(JsonObject section:sections) {
            List<JsonObject> parts=objects(section,"parts");if(parts.isEmpty())parts=List.of(section);
            for(JsonObject part:parts) {
                String owner=text(part,"nodeId"),contentId=text(part,"contentId");
                if(!contentId.isEmpty()&&!seenContent.add(contentId))continue;
                List<JsonObject> path=new ArrayList<>();Set<String> walking=new HashSet<>();String cursor=owner;
                while(!cursor.isEmpty()) {
                    JsonObject node=known.get(cursor);
                    if(node==null||!walking.add(cursor)||path.size()>=4)return legacy(sections);
                    path.add(node);cursor=text(node,"parentId");
                }
                if(path.isEmpty())return legacy(sections); // Never hide unbound saved prose.
                Collections.reverse(path);int common=0;
                while(common<Math.min(path.size(),openBase.size())&&text(path.get(common),"id").equals(openBase.get(common)))common++;
                openBase=new ArrayList<>(openBase.subList(0,common));open=new ArrayList<>(open.subList(0,common));
                for(JsonObject node:path.subList(common,path.size())) {
                    String base=text(node,"id"),id=base,parent=open.isEmpty()?"":open.getLast().id();
                    if(!used.add(id)){id=base+"/occurrence/"+(contentId.isEmpty()?++occurrence:contentId);used.add(id);}
                    Entry entry=new Entry(id,parent,text(node,"title"),open.size()+1,number(node,"page",1),
                        number(node,"endPage",number(node,"page",1)),new ArrayList<>());
                    out.add(entry);openBase.add(base);open.add(entry);if(!parent.isEmpty())parents.add(parent);
                }
                Entry entry=open.getLast();
                // Parallel units may deliver a later direct explanation of an
                // ancestor after its children. Give that occurrence its own
                // heading instead of moving the explanation above them.
                if(parents.contains(entry.id())&&entry.level()<4) {
                    String id=entry.id()+"/content/"+(contentId.isEmpty()?++occurrence:contentId);
                    Entry continuation=new Entry(id,entry.id(),text(part,"title"),entry.level()+1,
                        firstPage(part),lastPage(part),new ArrayList<>());
                    out.add(continuation);parents.add(entry.id());entry=continuation;
                }
                entry.content().add(part);
            }
        }
        return out.stream().map(e->new Entry(e.id(),e.parentId(),e.title(),e.level(),e.page(),e.endPage(),List.copyOf(e.content()))).toList();
    }

    private static List<Entry> legacy(List<JsonObject> sections) {
        List<Entry> out=new ArrayList<>();int i=0;
        for(JsonObject section:sections) {
            if(PdfWorkspace.isEmptyStudyPlaceholder(section))continue;
            String id="legacy-"+i++,title=text(section,"title");int page=firstPage(section);
            List<JsonObject> parts=objects(section,"parts");
            if(parts.isEmpty()||parts.size()==1&&text(parts.get(0),"title").equals(title)) {
                out.add(new Entry(id,"",title,1,page,lastPage(section),parts.isEmpty()?List.of(section):parts));continue;
            }
            out.add(new Entry(id,"",title,1,page,lastPage(section),List.of()));int j=0;
            for(JsonObject part:parts)out.add(new Entry(id+"-"+j++,id,text(part,"title"),2,
                firstPage(part),lastPage(part),List.of(part)));
        }
        return List.copyOf(out);
    }

    static String heading(Entry entry) {
        return heading(entry,false,false);
    }

    static String heading(Entry entry,boolean followsHeadingOnlyParent,boolean headingOnlyParent) {
        String id=PdfWorkspace.escape(entry.id()),title=PdfWorkspace.escape(entry.title());
        int level=Math.max(1,Math.min(4,entry.level()));
        String spacing=(followsHeadingOnlyParent?"margin-top:3px;":"")
            +(headingOnlyParent?"margin-bottom:0;":"");
        String anchor="<a name='outline:"+id+"'></a>";
        // An empty anchor between block headings creates an implied blank
        // paragraph in Swing HTML. Keep this child's anchor on its title row.
        return (followsHeadingOnlyParent?"":anchor)+"<h"+level
            +(spacing.isEmpty()?"":" style='"+spacing+"'")+">"
            +(followsHeadingOnlyParent?anchor:"")+title
            +" <small class='muted'><a href='page:"+entry.page()+"'>p."+entry.page()+"</a></small></h"+level+">";
    }

    static Map<String,Target> targets(Container root) {
        Map<String,Target> out=new LinkedHashMap<>();scan(root,out);return out;
    }
    private static void scan(Container root,Map<String,Target> out) {
        for(Component child:root.getComponents()) {
            if(child instanceof JEditorPane pane&&pane.getDocument() instanceof HTMLDocument document) {
                for(HTMLDocument.Iterator it=document.getIterator(HTML.Tag.A);it.isValid();it.next()) {
                    String name=String.valueOf(it.getAttributes().getAttribute(HTML.Attribute.NAME));
                    if(name.startsWith("outline:"))out.putIfAbsent(name.substring(8),new Target(pane,it.getStartOffset()));
                }
            } else if(child instanceof Container container)scan(container,out);
        }
    }
    static int firstPage(JsonObject block) {return pages(block).stream().min(Integer::compareTo).orElse(1);}
    static int lastPage(JsonObject block) {return pages(block).stream().max(Integer::compareTo).orElse(firstPage(block));}
    private static List<Integer> pages(JsonObject block) {
        List<Integer> pages=new ArrayList<>();
        if(block.has("visualPages"))for(JsonElement p:block.getAsJsonArray("visualPages"))if(p.isJsonPrimitive())pages.add(p.getAsInt());
        for(JsonObject evidence:objects(block,"evidence"))if(evidence.has("page"))pages.add(evidence.get("page").getAsInt());
        return pages;
    }
    static List<JsonObject> objects(JsonObject object,String key) {
        if(object==null||!object.has(key)||!object.get(key).isJsonArray())return List.of();
        List<JsonObject> out=new ArrayList<>();for(JsonElement e:object.getAsJsonArray(key))if(e.isJsonObject())out.add(e.getAsJsonObject());return out;
    }
    private static String text(JsonObject object,String key) {return object.has(key)&&object.get(key).isJsonPrimitive()?object.get(key).getAsString():"";}
    private static int number(JsonObject object,String key,int fallback) {try{return Math.max(1,object.get(key).getAsInt());}catch(RuntimeException ignored){return fallback;}}
}
