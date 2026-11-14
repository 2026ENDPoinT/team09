package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.Component;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.List;
import java.util.regex.*;
import javax.swing.*;
import javax.swing.text.html.*;

/** Local provenance and bounded adjacent source math; never part of visible chat or stored output. */
final class StudySelectionContext {
    static final String INHERITED="synesis.selectionOrigin";
    static final String PREFIX="synesis-study-origin-";
    static final int MAX_CONTEXT=480;
    record Source(String documentId,String title,List<Integer> pages) {}
    private record Origin(String id,int start,int end) {}
    private static final Pattern ANCHOR=Pattern.compile("<a name='("+PREFIX+"[A-Za-z0-9_-]+)'></a>");
    private static final Pattern MATH=Pattern.compile("(?s)\\$\\$.*?\\$\\$|(?<!\\\\)\\$(?:\\\\.|[^$])*\\$");

    static String register(Map<String,Source> sources,String key,Source source) {
        String id=PREFIX+Base64.getUrlEncoder().withoutPadding().encodeToString(key.getBytes(StandardCharsets.UTF_8));
        sources.put(id,source);return "<a name='"+id+"'></a>";
    }
    static String lastOrigin(String html,String inherited) {
        Matcher matcher=ANCHOR.matcher(html);while(matcher.find())inherited=matcher.group(1);return inherited;
    }
    static void inherit(JComponent component,String origin){component.putClientProperty(INHERITED,origin);}
    private static Origin origin(StudyHtmlPane pane,int offset,Map<String,Source> sources) {
        String id=null;int start=0,end=pane.getDocument().getLength();
        for(Component c=pane;c!=null;c=c.getParent())if(c instanceof JComponent component
                &&component.getClientProperty(INHERITED) instanceof String inherited){id=inherited;break;}
        if(pane.getDocument() instanceof HTMLDocument document)
            for(HTMLDocument.Iterator a=document.getIterator(HTML.Tag.A);a.isValid();a.next()) {
                Object name=a.getAttributes().getAttribute(HTML.Attribute.NAME);
                if(name==null||!sources.containsKey(name.toString()))continue;
                if(a.getStartOffset()<=offset){if(!sameItem(id,name.toString(),sources))start=a.getEndOffset();id=name.toString();}
                else if(!sameItem(id,name.toString(),sources)){end=a.getStartOffset();break;}
            }
        return new Origin(id,start,end);
    }
    private static boolean sameItem(String first,String second,Map<String,Source> sources) {
        Source a=sources.get(first),b=sources.get(second);
        return a!=null&&b!=null&&a.documentId().equals(b.documentId())&&a.title().equals(b.title());
    }
    static JsonObject capture(List<StudyHtmlPane> panes,String selected,String tab,Map<String,Source> sources) {
        JsonObject result=new JsonObject();
        int first=-1,last=-1;
        LinkedHashSet<Integer> pages=new LinkedHashSet<>();String title="",documentId="";
        for(int i=0;i<panes.size();i++) {
            StudyHtmlPane pane=panes.get(i);if(pane.getSelectionStart()==pane.getSelectionEnd())continue;
            if(first<0)first=i;last=i;
            Origin origin=origin(pane,pane.getSelectionStart(),sources);Source source=sources.get(origin.id());
            if(source!=null){if(title.isEmpty()){title=source.title();documentId=source.documentId();}pages.addAll(source.pages());}
            if(source!=null&&source.pages().isEmpty())
                for(Component c=pane;c!=null;c=c.getParent())if(c instanceof JComponent component
                        &&component.getClientProperty(INHERITED) instanceof String inherited) {
                    Source parent=sources.get(inherited);if(parent!=null&&!parent.pages().isEmpty()){pages.addAll(parent.pages());break;}
                }
            if(pane.getDocument() instanceof HTMLDocument document)
                for(HTMLDocument.Iterator a=document.getIterator(HTML.Tag.A);a.isValid();a.next()) {
                    if(a.getStartOffset()<pane.getSelectionStart()||a.getStartOffset()>=pane.getSelectionEnd())continue;
                    Object name=a.getAttributes().getAttribute(HTML.Attribute.NAME);Source included=name==null?null:sources.get(name.toString());
                    if(included!=null)pages.addAll(included.pages());
                }
        }
        if(first<0||title.isEmpty())return result;
        result.addProperty("origin",tab);result.addProperty("title",clip(title,80));
        if(!documentId.isEmpty())result.addProperty("documentId",documentId);
        JsonArray locations=new JsonArray();pages.stream().filter(p->p>0).limit(4).forEach(locations::add);
        if(!locations.isEmpty())result.add("pages",locations);
        if(selected.length()<1200) {
            StudyHtmlPane firstPane=panes.get(first),lastPane=panes.get(last);
            String firstId=origin(firstPane,firstPane.getSelectionStart(),sources).id();
            List<String> preceding=new ArrayList<>();int used=0;
            for(int i=first;i>=0&&i>=first-3&&used<360;i--) {
                StudyHtmlPane pane=panes.get(i);int end=i==first?pane.getSelectionStart():pane.getDocument().getLength();
                Origin item=origin(pane,Math.max(0,end-1),sources);
                if(!Objects.equals(firstId,item.id())&&!sameItem(firstId,item.id(),sources))break;
                String text=pane.selectionMarkdown(Math.max(item.start(),end-300),end);
                if(text!=null&&!text.isBlank()&&!selected.contains(text.strip())) {
                    text=bounded(text,360-used);preceding.add(0,text);used+=text.length();
                }
            }
            int end=lastPane.getSelectionEnd();Origin item=origin(lastPane,Math.max(lastPane.getSelectionStart(),end-1),sources);
            String following=lastPane.selectionMarkdown(end,Math.min(item.end(),end+100));
            String context=bounded(String.join("\n",preceding)+"\n"+Objects.toString(following,""),MAX_CONTEXT);
            if(!context.isBlank()&&!selected.contains(context))result.addProperty("context",context);
        }
        return result;
    }
    /** Truncate prose only; keep each included formula whole, or omit it. */
    static String bounded(String markdown,int limit) {
        StringBuilder out=new StringBuilder();Matcher math=MATH.matcher(markdown);int cursor=0;
        while(math.find()) {
            out.append(clip(markdown.substring(cursor,math.start()),Math.max(0,limit-out.length())));
            if(math.end()-math.start()<=limit-out.length())out.append(math.group());
            cursor=math.end();if(out.length()>=limit)break;
        }
        if(out.length()<limit)out.append(clip(markdown.substring(cursor),limit-out.length()));
        return out.toString().strip();
    }
    private static String clip(String text,int limit) {
        if(text.length()<=limit)return text;
        if(limit>0&&Character.isHighSurrogate(text.charAt(limit-1)))limit--;
        return text.substring(0,Math.max(0,limit));
    }
    private StudySelectionContext() {}
}
