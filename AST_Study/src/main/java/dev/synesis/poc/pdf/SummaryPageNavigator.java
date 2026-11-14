package dev.synesis.poc.pdf;

import javax.swing.*;
import javax.swing.text.html.*;
import java.awt.*;
import java.util.TreeMap;

/** Finds the first real citation after the overview, including split HTML/math layouts. */
final class SummaryPageNavigator {
    record Target(JEditorPane pane,int offset) {}
    private SummaryPageNavigator() {}
    static Target find(Container content,int page){return scan(content,page,new boolean[]{false});}
    /** Cover/title pages may have no explanation. Continue at the next explained page. */
    static Target findNearest(Container content,int page){
        TreeMap<Integer,Target> targets=new TreeMap<>();
        collect(content,targets,new boolean[]{false});
        var next=targets.ceilingEntry(page);
        return next!=null?next.getValue():targets.isEmpty()?null:targets.lastEntry().getValue();
    }
    private static void collect(Container container,TreeMap<Integer,Target> targets,boolean[] inContent){
        for(Component child:container.getComponents()){
            if(!child.isVisible())continue;
            if(child instanceof JEditorPane pane&&pane.getDocument() instanceof HTMLDocument doc){
                for(HTMLDocument.Iterator it=doc.getIterator(HTML.Tag.A);it.isValid();it.next()){
                    if("synesis-summary-content".equals(it.getAttributes().getAttribute(HTML.Attribute.NAME)))inContent[0]=true;
                    Object href=it.getAttributes().getAttribute(HTML.Attribute.HREF);
                    if(inContent[0]&&href instanceof String link&&link.startsWith("page:")){
                        try{targets.putIfAbsent(Integer.parseInt(link.substring(5)),new Target(pane,it.getStartOffset()));}
                        catch(NumberFormatException ignored){}
                    }
                }
            }else if(child instanceof Container nested)collect(nested,targets,inContent);
        }
    }
    private static Target scan(Container container,int page,boolean[] inContent){
        for(Component child:container.getComponents()){
            if(child instanceof JEditorPane pane&&pane.getDocument() instanceof HTMLDocument doc){
                for(HTMLDocument.Iterator it=doc.getIterator(HTML.Tag.A);it.isValid();it.next()){
                    Object name=it.getAttributes().getAttribute(HTML.Attribute.NAME);
                    if("synesis-summary-content".equals(name))inContent[0]=true;
                    if(inContent[0]&&("page:"+page).equals(it.getAttributes().getAttribute(HTML.Attribute.HREF)))return new Target(pane,it.getStartOffset());
                }
            }else if(child instanceof Container nested){Target target=scan(nested,page,inContent);if(target!=null)return target;}
        }return null;
    }
}
